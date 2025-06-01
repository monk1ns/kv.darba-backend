import os
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship
from sqlalchemy.orm import joinedload
import jwt
from sqlalchemy import func
import datetime
from functools import wraps
import bcrypt
import logging
from dotenv import load_dotenv
from dateutil import parser
import io
import requests
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.units import cm
from io import BytesIO
from werkzeug.security import generate_password_hash
load_dotenv()

app = Flask(__name__)


from flask_cors import CORS


app = Flask(__name__)  

CORS(app, resources={r"/*": {
    "origins": "*",
    "supports_credentials": True,
    "allow_headers": ["Content-Type", "Authorization"],
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"]
    
}})
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


SECRET_KEY = "your_secret_key"


logging.basicConfig(level=logging.DEBUG)



class Employee(db.Model):
    __tablename__ = 'employees'
    id = db.Column(db.Integer, primary_key=True)
    vards = db.Column(db.String(15))
    uzvards = db.Column(db.String(15))
    amats = db.Column(db.String(20))
    kods = db.Column(db.Integer)
    status = db.Column(db.String(10))
    token = db.Column(db.String(512))
    password = db.Column(db.String(200))

    shifts = db.relationship("Shift", backref="employee")
    orders = db.relationship("Order", backref="employee")

    def serialize(self):
        return {
            "id": self.id,
            "vards": self.vards,
            "uzvards": self.uzvards,
            "amats": self.amats,
            "kods": self.kods,
            "status": self.status
        }



class Shift(db.Model):
    __tablename__ = 'shifts'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'))
    start_time = db.Column(db.DateTime(timezone=True))
    end_time = db.Column(db.DateTime(timezone=True)) 


class Material(db.Model):
    __tablename__ = 'materials'
    id = db.Column(db.Integer, primary_key=True)
    nosaukums = db.Column(db.String(50))
    noliktava = db.Column(db.String(20))
    vieta = db.Column(db.String(20))
    vieniba = db.Column(db.String(20))
    daudzums = db.Column(db.Float)
    version = db.Column(db.Integer, default=1)

    order_links = db.relationship(
    "OrderMaterial",
    backref="material",
    cascade="all, delete-orphan",
    passive_deletes=True
)



class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    nosaukums = db.Column(db.String(50))
    daudzums = db.Column(db.Float)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True)
    status = db.Column(db.String(20), default="Nav sākts")      
   
    materials = db.relationship("OrderMaterial", backref="order",  cascade="all, delete-orphan")

def to_dict(self):
        return {
            'id': self.id,
            'nosaukums': self.nosaukums,
            'daudzums': self.daudzums,
            'status': self.status,
        }


class OrderMaterial(db.Model):
    __tablename__ = 'order_materials'
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), primary_key=True)
    material_id = db.Column(
    db.Integer, 
    db.ForeignKey('materials.id', ondelete='CASCADE'),
    primary_key=True
)

    daudzums = db.Column(db.Float)




def generate_token(user_id):
    expiration = datetime.datetime.utcnow() + datetime.timedelta(hours=1)
    payload = {'user_id': user_id, 'exp': expiration}
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')


def token_required(f):
    @wraps(f)
    def decorator(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token or not token.startswith("Bearer "):
            return jsonify({"error": "Token is missing or incorrect format!"}), 403

        token = token[7:]
        try:
            decoded = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            user = Employee.query.get(decoded['user_id'])
            if not user:
                return jsonify({"error": "User not found"}), 404
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 403

        return f(user, *args, **kwargs)
    return decorator

@app.route('/api/shifts/stats', methods=['OPTIONS'])
def shifts_stats_options():
    response = jsonify({'message': 'CORS preflight'})
    response.headers.add('Access-Control-Allow-Origin', 'https://kv-darbs.vercel.app')
    response.headers.add('Access-Control-Allow-Headers', 'Authorization, Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
    return response, 200


@app.route('/api/shifts/stats', methods=['GET'])
@token_required
def get_shifts_stats(current_user):
    try:
        start = request.args.get('start')
        end = request.args.get('end')

        start_date = parser.parse(start) if start else None
        end_date = parser.parse(end) if end else None

        employees = Employee.query.options(joinedload(Employee.shifts)).all()
        stats = []

        for emp in employees:
            for shift in emp.shifts:
                if not shift.start_time or not shift.end_time:
                    continue
                if start_date and shift.start_time < start_date:
                    continue
                if end_date and shift.end_time > end_date:
                    continue

                duration_hours = (shift.end_time - shift.start_time).total_seconds() / 3600
                stats.append({
                    "id": emp.id,
                    "vards": emp.vards,
                    "uzvards": emp.uzvards,
                    "amats": emp.amats,
                    "hours": round(duration_hours, 2),
                    "start_time": shift.start_time.isoformat() if shift.start_time else None,
                    "end_time": shift.end_time.isoformat() if shift.end_time else None
                })

        response = jsonify(stats)
        response.headers.add('Access-Control-Allow-Origin', 'https://kv-darbs.vercel.app')
        return response, 200

    except Exception as e:
        logging.error(f"Stats error: {str(e)}")
        return jsonify({"error": "Stats generation failed"}), 500 



@app.route("/api/stats/materials", methods=["GET"])
@token_required
def get_material_stats(current_user):
    try:
        results = db.session.query(
            Material.id,
            Material.nosaukums,
            db.func.sum(OrderMaterial.daudzums * Order.daudzums).label("total")
        ).join(OrderMaterial, Material.id == OrderMaterial.material_id) \
         .join(Order, Order.id == OrderMaterial.order_id) \
         .group_by(Material.id, Material.nosaukums) \
         .all()

        data = [
            {
                "id": material_id,
                "nosaukums": nosaukums,
                "totalUsed": float(total) if total is not None else 0
            }
            for material_id, nosaukums, total in results
        ]

        return jsonify(data), 200

    except Exception as e:
        logging.error(f"Stats error: {str(e)}")
        return jsonify({"error": "Neizdevās iegūt statistiku"}), 500




@app.route("/login", methods=["POST"])
def login():
    try:
        data = request.get_json()
        print("Received data:", data)  
        if not data:
            return jsonify({"error": "No JSON body received"}), 400

        kods = data.get("kods")
        if not kods:
            return jsonify({"error": "Kods not provided"}), 400

        
        try:
            if isinstance(kods, str):
                kods = int(kods)
        except ValueError:
            return jsonify({"error": "Nederīgs koda formāts"}), 400

        user = Employee.query.filter_by(kods=kods).first()
        if not user:
            return jsonify({"error": "Nepareizs kods"}), 401

        token = generate_token(user.id)
        user.token = token
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Pieteikšanās veiksmīga",
            "token": token,
            "user": {
                "id": user.id,
                "vards": user.vards,
                "uzvards": user.uzvards,
                "amats": user.amats
            },
            "redirect": "/admin" if user.amats == "Administrators" else "/home"
        }), 200
    except Exception as e:
        print("Error during login:", str(e))
        return jsonify({"error": "Server error"}), 500

@app.route("/login/password", methods=["POST"])
def login_with_password():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON body received"}), 400

        kods = data.get("kods")
        password = data.get("password")
        
        if not kods or not password:
            return jsonify({"error": "Kods or password not provided"}), 400

        
        try:
            if isinstance(kods, str):
                kods = int(kods)
        except ValueError:
            return jsonify({"error": "Nederīgs koda formāts"}), 400
        
        user = Employee.query.filter_by(kods=kods).first()
        if not user:
            return jsonify({"error": "User not found"}), 404

        if not bcrypt.checkpw(password.encode('utf-8'), user.password.encode('utf-8')):
            return jsonify({"error": "Incorrect password"}), 401

        token = generate_token(user.id)
        user.token = token
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Login successful",
            "token": token,
            "user": {
                "id": user.id,
                "vards": user.vards,
                "uzvards": user.uzvards,
                "amats": user.amats
            },
            "redirect": "/admin" if user.amats == "Administrators" else "/home"
        }), 200

    except Exception as e:
        return jsonify({"error": "Server error", "details": str(e)}), 500 
@app.route("/logout", methods=["POST"])
@token_required
def logout(current_user):
    current_user.token = None
    db.session.commit()
    return jsonify({"success": True, "message": "Logout successful"}), 200


@app.route("/materials", methods=["GET"])
@token_required
def get_materials(current_user):
    try:
        materials = Material.query.all()
        return jsonify([{
            'id': material.id,
            'nosaukums': material.nosaukums,
            'noliktava': material.noliktava,
            'vieta': material.vieta,
            'vieniba': material.vieniba,
            'daudzums': material.daudzums,
            'version': material.version
        } for material in materials]), 200
    except Exception as e:
        logging.error(f"Error getting materials: {str(e)}")
        return jsonify({"error": "Neizdevās iegūt materiālus", "details": str(e)}), 500
@app.route("/materials/<int:material_id>", methods=["GET"])
@token_required
def get_material(current_user, material_id):
    try:
        material = Material.query.get(material_id)
        if not material:
            return jsonify({"error": "Materiāls nav atrasts"}), 404
            
        return jsonify({
            'id': material.id,
            'nosaukums': material.nosaukums,
            'noliktava': material.noliktava,
            'vieta': material.vieta,
            'vieniba': material.vieniba,
            'daudzums': material.daudzums,
            'version': material.version
        }), 200
    except Exception as e:
        logging.error(f"Error getting material: {str(e)}")
        return jsonify({"error": "Neizdevās iegūt materiālu", "details": str(e)}), 500




@app.route("/orders", methods=["GET"])
@token_required
def get_orders(current_user):
    try:
        orders = Order.query.all()
        orders_list = []
        
        for order in orders:
            # Iegūstam materiālus ar versijām
            materials = []
            for order_material in order.materials:
                material = Material.query.get(order_material.material_id)
                if material:
                    materials.append({
                        'id': material.id,
                        'nosaukums': material.nosaukums,
                        'noliktava': material.noliktava,
                        'vieta': material.vieta,
                        'vieniba': material.vieniba,
                        'daudzums': material.daudzums,
                        'version': material.version,
                        'quantity': order_material.quantity,
                        'material_version': order_material.material_version
                    })

            orders_list.append({
                'id': order.id,
                'nosaukums': order.nosaukums,
                'daudzums': order.daudzums,
                'employee_id': order.employee_id,
                'status': order.status,
                'created_at': order.created_at.isoformat(),
                'updated_at': order.updated_at.isoformat(),
                'materials': materials
            })

        return jsonify(orders_list), 200

    except Exception as e:
        logging.error(f"Error getting orders: {str(e)}")
        return jsonify({"error": "Neizdevās iegūt pasūtījumus", "details": str(e)}), 500


@app.route("/orders/<int:order_id>", methods=["GET"])
@token_required
def get_order(current_user, order_id):
    try:
        order = Order.query.get(order_id)
        if not order:
            return jsonify({'error': 'Pasūtījums nav atrasts'}), 404

        # Iegūstam materiālus ar versijām
        materials = []
        for order_material in order.materials:
            material = Material.query.get(order_material.material_id)
            if material:
                materials.append({
                    'id': material.id,
                    'nosaukums': material.nosaukums,
                    'noliktava': material.noliktava,
                    'vieta': material.vieta,
                    'vieniba': material.vieniba,
                    'daudzums': material.daudzums,
                    'version': material.version,
                    'quantity': order_material.quantity,
                    'material_version': order_material.material_version
                })

        return jsonify({
            'id': order.id,
            'nosaukums': order.nosaukums,
            'daudzums': order.daudzums,
            'employee_id': order.employee_id,
            'status': order.status,
            'created_at': order.created_at.isoformat(),
            'updated_at': order.updated_at.isoformat(),
            'materials': materials
        }), 200

    except Exception as e:
        logging.error(f"Error getting order: {str(e)}")
        return jsonify({"error": "Neizdevās iegūt pasūtījumu", "details": str(e)}), 500

@app.route("/orders/<int:order_id>/accept", methods=["PATCH"])
@token_required
def accept_order(current_user, order_id):
    try:
        order = Order.query.get(order_id)
        if not order:
            return jsonify({'error': 'Pasūtījums nav atrasts'}), 404

        if order.status != 'pending':
            return jsonify({'error': 'Pasūtījums jau ir apstrādāts'}), 400

        # Pārbaudam materiālu pieejamību un versijas
        for order_material in order.materials:
            material = Material.query.get(order_material.material_id)
            if not material:
                return jsonify({'error': f'Materiāls ar ID {order_material.material_id} nav atrasts'}), 404
            
            # Pārbaudam versiju
            if material.version != order_material.material_version:
                return jsonify({
                    'error': f'Materiāla "{material.nosaukums}" dati ir mainījušies. Lūdzu, atsvaidziniet lapu un mēģiniet vēlreiz.'
                }), 409
            
            # Pārbaudam daudzumu
            if material.daudzums < order_material.quantity:
                return jsonify({
                    'error': f'Nepietiek materiāla "{material.nosaukums}". Pieejams: {material.daudzums} {material.vieniba}'
                }), 400

        # Atjauninām materiālu daudzumus un versijas
        for order_material in order.materials:
            material = Material.query.get(order_material.material_id)
            material.daudzums -= order_material.quantity
            material.version += 1

        # Atjauninām pasūtījuma statusu
        order.status = 'accepted'
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Pasūtījums pieņemts",
            "order_id": order.id
        }), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error accepting order: {str(e)}")
        return jsonify({"error": "Neizdevās pieņemt pasūtījumu", "details": str(e)}), 500

@app.route("/orders/<int:order_id>/finish", methods=["PATCH"])
@token_required
def finish_order(current_user, order_id):
    try:
        order = Order.query.get(order_id)
        if not order:
            return jsonify({'error': 'Pasūtījums nav atrasts'}), 404

        if order.status != 'accepted':
            return jsonify({'error': 'Pasūtījums nav pieņemts'}), 400

        # Pārbaudam materiālu versijas
        for order_material in order.materials:
            material = Material.query.get(order_material.material_id)
            if not material:
                return jsonify({'error': f'Materiāls ar ID {order_material.material_id} nav atrasts'}), 404
            
            # Pārbaudam versiju
            if material.version != order_material.material_version:
                return jsonify({
                    'error': f'Materiāla "{material.nosaukums}" dati ir mainījušies. Lūdzu, atsvaidziniet lapu un mēģiniet vēlreiz.'
                }), 409

        # Atjauninām pasūtījuma statusu
        order.status = 'finished'
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Pasūtījums pabeigts",
            "order_id": order.id
        }), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error finishing order: {str(e)}")
        return jsonify({"error": "Neizdevās pabeigt pasūtījumu", "details": str(e)}), 500

@app.route("/employees", methods=["GET"])
@token_required
def get_employees(current_user):
    try:
        employees = Employee.query.all()
        employees_list = [{
            "id": employee.id,
            "vards": employee.vards,
            "uzvards": employee.uzvards,
            "amats": employee.amats,
            "kods": employee.kods,
            "status": employee.status
        } for employee in employees]
        return jsonify({"success": True, "employees": employees_list}), 200
    except Exception as e:
        logging.error(f"Error fetching employees: {str(e)}")
        return jsonify({"error": "Failed to fetch employees", "details": str(e)}), 500
@app.route("/employees", methods=["POST"])
@token_required
def add_employee(current_user):
    try:
        data = request.get_json()

        password_hash = None
        if data["amats"].lower() == "administrators":
            raw_password = data.get("password")
            if not raw_password:
                return jsonify({"error": "Parole ir obligāta administratoram"}), 400
            password_hash = bcrypt.hashpw(raw_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        new_employee = Employee(
            vards=data["vards"],
            uzvards=data["uzvards"],
            amats=data["amats"],
            kods=data["kods"],
            status=data["status"],
            password=password_hash
        )

        db.session.add(new_employee)
        db.session.commit()
        return jsonify({"success": True, "message": "Darbinieks pievienots"}), 201
    except Exception as e:
        return jsonify({"error": "Failed to add employee", "details": str(e)}), 500
@app.route("/employees/<int:id>", methods=["PUT"])
@token_required
def update_employee(current_user, id):
    try:
        data = request.get_json()
        employee = Employee.query.get(id)
        if not employee:
            return jsonify({"error": "Darbinieks nav atrasts"}), 404

        employee.vards = data["vards"]
        employee.uzvards = data["uzvards"]
        employee.amats = data["amats"]
        employee.kods = data["kods"]
        employee.status = data["status"]
        
        
        if "password" in data and data["password"]:
            password_hash = bcrypt.hashpw(data["password"].encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
            employee.password = password_hash

        db.session.commit()
        return jsonify({"success": True, "message": "Darbinieks atjaunināts"}), 200
    except Exception as e:
        return jsonify({"error": "Failed to update employee", "details": str(e)}), 500

@app.route("/employees/<int:id>", methods=["DELETE"])
@token_required
def delete_employee(current_user, id):
    try:
        employee = Employee.query.get(id)
        if not employee:
            return jsonify({"error": "Darbinieks nav atrasts"}), 404

        db.session.delete(employee)
        db.session.commit()
        return jsonify({"success": True, "message": "Darbinieks dzēsts"}), 200
    except Exception as e:
        return jsonify({"error": "Failed to delete employee", "details": str(e)}), 500
@app.route("/orders/<int:order_id>", methods=["PUT"])
@token_required
def update_order(current_user, order_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Nav datu'}), 400

        order = Order.query.get(order_id)
        if not order:
            return jsonify({'error': 'Pasūtījums nav atrasts'}), 404

        # Pārbaudam materiālu pieejamību un versijas
        if 'materials' in data:
            materials_data = []
            for material_data in data['materials']:
                material = Material.query.get(material_data['id'])
                if not material:
                    return jsonify({'error': f'Materiāls ar ID {material_data["id"]} nav atrasts'}), 404
                
                # Pārbaudam versiju
                if material.version != material_data.get('version'):
                    return jsonify({
                        'error': f'Materiāla "{material.nosaukums}" dati ir mainījušies. Lūdzu, atsvaidziniet lapu un mēģiniet vēlreiz.'
                    }), 409
                
                # Pārbaudam daudzumu
                if material.daudzums < material_data['quantity']:
                    return jsonify({
                        'error': f'Nepietiek materiāla "{material.nosaukums}". Pieejams: {material.daudzums} {material.vieniba}'
                    }), 400
                
                materials_data.append({
                    'material': material,
                    'quantity': material_data['quantity']
                })

            # Atjauninām materiālus
            # Vispirms atgriežam vecos daudzumus
            for order_material in order.materials:
                material = Material.query.get(order_material.material_id)
                material.daudzums += order_material.quantity
                material.version += 1

            # Izdzēšam vecos materiālus
            OrderMaterial.query.filter_by(order_id=order.id).delete()

            # Pievienojam jaunos materiālus
            for material_data in materials_data:
                order_material = OrderMaterial(
                    order_id=order.id,
                    material_id=material_data['material'].id,
                    quantity=material_data['quantity'],
                    material_version=material_data['material'].version
                )
                db.session.add(order_material)
                
                # Atjauninām materiāla daudzumu un versiju
                material_data['material'].daudzums -= material_data['quantity']
                material_data['material'].version += 1

        # Atjauninām pārējos pasūtījuma datus
        if 'nosaukums' in data:
            order.nosaukums = data['nosaukums']
        if 'daudzums' in data:
            order.daudzums = float(data['daudzums'])
        if 'status' in data:
            order.status = data['status']
        if 'employee_id' in data:
            order.employee_id = data['employee_id']

        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Pasūtījums atjaunināts",
            "order_id": order.id
        }), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating order: {str(e)}")
        return jsonify({"error": "Neizdevās atjaunināt pasūtījumu", "details": str(e)}), 500

@app.route("/materials", methods=["POST"])
@token_required
def create_material(current_user):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Nav datu'}), 400

        required_fields = ['nosaukums', 'noliktava', 'vieta', 'vieniba', 'daudzums']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Trūkst lauka: {field}'}), 400

        if float(data['daudzums']) < 0.01:
            return jsonify({'error': 'Daudzumam jābūt vismaz 0.01'}), 400

        new_material = Material(
            nosaukums=data['nosaukums'],
            noliktava=data['noliktava'],
            vieta=data['vieta'],
            vieniba=data['vieniba'],
            daudzums=float(data['daudzums']),
            version=1  # Inicializējam versiju
        )

        db.session.add(new_material)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Materiāls izveidots",
            "material": {
                'id': new_material.id,
                'nosaukums': new_material.nosaukums,
                'noliktava': new_material.noliktava,
                'vieta': new_material.vieta,
                'vieniba': new_material.vieniba,
                'daudzums': new_material.daudzums,
                'version': new_material.version
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating material: {str(e)}")
        return jsonify({"error": "Neizdevās izveidot materiālu", "details": str(e)}), 500

@app.route("/materials/<int:material_id>", methods=["PUT"])
@token_required
def update_material(current_user, material_id):
    try:
        data = request.get_json()
        material = Material.query.get(material_id)
        
        if not material:
            return jsonify({"error": "Materiāls nav atrasts"}), 404

        # Pārbaudam versiju
        if 'version' in data and material.version != data['version']:
            return jsonify({
                "error": f'Materiāla "{material.nosaukums}" dati ir mainījušies. Lūdzu, atsvaidziniet lapu un mēģiniet vēlreiz.'
            }), 409

        # Atjauninām materiāla datus
        for key, value in data.items():
            if key != 'version' and hasattr(material, key):
                setattr(material, key, value)
        
        # Palielinām versiju
        material.version += 1
        
        db.session.commit()
        return jsonify({
            "success": True,
            "message": "Materiāls atjaunināts",
            "version": material.version
        }), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating material: {str(e)}")
        return jsonify({"error": "Neizdevās atjaunināt materiālu", "details": str(e)}), 500

@app.route("/materials/<int:material_id>", methods=["DELETE"])
@token_required
def delete_material(current_user, material_id):
    try:
        material = Material.query.get(material_id)
        if not material:
            return jsonify({"error": "Materiāls nav atrasts"}), 404
        db.session.delete(material)
        db.session.commit()
        return jsonify({"success": True, "message": "Materiāls izdzēsts"}), 200
    except Exception as e:
        logging.error(f"Error deleting material: {str(e)}")
        return jsonify({"error": "Failed to delete material", "details": str(e)}), 500

@app.route("/orders", methods=["POST"])
@token_required
def create_order(current_user):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Nav datu'}), 400

        required_fields = ['nosaukums', 'daudzums', 'employee_id', 'materials']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Trūkst lauka: {field}'}), 400

        # Pārbaudam materiālu pieejamību un versijas
        materials_data = []
        for material_data in data['materials']:
            material = Material.query.get(material_data['id'])
            if not material:
                return jsonify({'error': f'Materiāls ar ID {material_data["id"]} nav atrasts'}), 404
            
            # Pārbaudam versiju
            if material.version != material_data.get('version'):
                return jsonify({
                    'error': f'Materiāla "{material.nosaukums}" dati ir mainījušies. Lūdzu, atsvaidziniet lapu un mēģiniet vēlreiz.'
                }), 409
            
            # Pārbaudam daudzumu
            if material.daudzums < material_data['quantity']:
                return jsonify({
                    'error': f'Nepietiek materiāla "{material.nosaukums}". Pieejams: {material.daudzums} {material.vieniba}'
                }), 400
            
            materials_data.append({
                'material': material,
                'quantity': material_data['quantity']
            })

        # Izveidojam pasūtījumu
        order = Order(
            nosaukums=data['nosaukums'],
            daudzums=float(data['daudzums']),
            employee_id=data['employee_id'],
            status='pending'
        )
        db.session.add(order)
        db.session.flush()  # Lai iegūtu order.id

        # Pievienojam materiālus pasūtījumam
        for material_data in materials_data:
            order_material = OrderMaterial(
                order_id=order.id,
                material_id=material_data['material'].id,
                quantity=material_data['quantity'],
                material_version=material_data['material'].version
            )
            db.session.add(order_material)
            
            # Atjauninām materiāla daudzumu un versiju
            material_data['material'].daudzums -= material_data['quantity']
            material_data['material'].version += 1

        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Pasūtījums izveidots",
            "order_id": order.id
        }), 201

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error creating order: {str(e)}")
        return jsonify({"error": "Neizdevās izveidot pasūtījumu", "details": str(e)}), 500


@app.route("/orders/<int:order_id>", methods=["DELETE"])
@token_required
def delete_order(current_user, order_id):
    try:
        order = Order.query.get(order_id)
        if not order:
            return jsonify({'error': 'Pasūtījums nav atrasts'}), 404

        # Atgriežam materiālu daudzumus
        for order_material in order.materials:
            material = Material.query.get(order_material.material_id)
            if material:
                material.daudzums += order_material.quantity
                material.version += 1

        # Izdzēšam pasūtījumu
        db.session.delete(order)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Pasūtījums dzēsts"
        }), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error deleting order: {str(e)}")
        return jsonify({"error": "Neizdevās dzēst pasūtījumu", "details": str(e)}), 500

@app.route('/api/shifts/start', methods=['POST'])
@token_required
def start_shift(current_user):
    try:
        
        active_shift = Shift.query.filter(
            Shift.employee_id == current_user.id,
            Shift.end_time.is_(None)  
        ).first()

        if active_shift:
            return jsonify({"error": "Jums jau ir aktīva maiņa."}), 400

        
        new_shift = Shift(
            employee_id=current_user.id,
            start_time=datetime.datetime.utcnow(),  
            end_time=None  
        )
        db.session.add(new_shift)
        db.session.commit()

        return jsonify({
            "id": new_shift.id,
            "message": "Maiņa sākta.",
            "start_time": new_shift.start_time.isoformat()
        }), 201

    except Exception as e:
        logging.error(f"Kļūda sākot maiņu: {str(e)}")
        return jsonify({"error": "Servera kļūda"}), 500

@app.route('/api/shifts/end/<int:shift_id>', methods=['PUT'])
@token_required
def end_shift(current_user, shift_id):
    try:
        shift = Shift.query.get(shift_id)
        if not shift:
            return jsonify({"error": "Maiņa nav atrasta."}), 404

        if shift.employee_id != current_user.id:
            return jsonify({"error": "Nav tiesību pabeigt šo maiņu."}), 403

        if shift.end_time is not None:
            return jsonify({"error": "Maiņa jau ir pabeigta."}), 400

        
        shift.end_time = datetime.datetime.utcnow()
        db.session.commit()

        return jsonify({
            "message": "Maiņa pabeigta.",
            "start_time": shift.start_time.isoformat(),
            "end_time": shift.end_time.isoformat()
        }), 200

    except Exception as e:
        logging.error(f"Kļūda beidzot maiņu: {str(e)}")
        return jsonify({"error": "Servera kļūda"}), 500

@app.route('/materials/search')
def search_materials():
    search_term = request.args.get('q', '')
    materials = Material.query.filter(
        Material.nosaukums.ilike(f'%{search_term}%')
    ).limit(10).all()
    return jsonify([m.to_dict() for m in materials])

@app.route('/orders/<int:order_id>/materials')
def get_order_materials(order_id):
    materials = db.session.query(
        Material.nosaukums,
        OrderMaterial.quantity,
        Material.vieniba
    ).join(OrderMaterial).filter(
        OrderMaterial.order_id == order_id
    ).all()
    
    result = [{
        'nosaukums': m.nosaukums,
        'daudzums': m.quantity,
        'vieniba': m.vieniba
    } for m in materials]
    
    return jsonify(result)
  

def download_font(url, save_path):
    response = requests.get(url)
    if response.status_code == 200:
        with open(save_path, 'wb') as f:
            f.write(response.content)
    else:
        raise Exception(f"Failed to download font: {response.status_code}")

def create_pdf_content(report_type, data):
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm
    )

    
    font_path = os.path.join(os.path.dirname(__file__), 'fonts', 'DejaVuSans.ttf')
    pdfmetrics.registerFont(TTFont('DejaVuSans', font_path))

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name='Latvian',
        fontName='DejaVuSans',
        fontSize=12,
        leading=14
    ))
    styles.add(ParagraphStyle(
        name='LatvianTitle',
        fontName='DejaVuSans',
        fontSize=16,
        leading=18,
        spaceAfter=30
    ))
    
    content = []
    
    
    titles = {
        'orders': 'Pasūtījumu Atskaite',
        'materials': 'Materiālu Atskaite',
        'workers': 'Darbinieku Atskaite',
        'shifts': 'Maiņu Atskaite'
    }
    
    content.append(Paragraph(titles.get(report_type, 'Atskaite'), styles['LatvianTitle']))
    content.append(Spacer(1, 20))
    
    
    if report_type == 'orders':
        if data:
            table_data = [['Nosaukums', 'Daudzums', 'Statuss']]
            for order in data:
                table_data.append([
                    order.get('nosaukums', ''),
                    str(order.get('daudzums', '')),
                    order.get('status', '')
                ])
            table = Table(table_data, colWidths=[8*cm, 3*cm, 3*cm])
            table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'DejaVuSans'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('PADDING', (0, 0), (-1, -1), 6),
            ]))
            content.append(table)
        else:
            content.append(Paragraph("Nav pasūtījumu datu", styles['Latvian']))
            
    elif report_type == 'materials':
        if data:
            table_data = [['Nosaukums', 'Daudzums', 'Vienība', 'Noliktava']]
            for material in data:
                table_data.append([
                    material.get('nosaukums', ''),
                    str(material.get('daudzums', '')),
                    material.get('vieniba', ''),
                    material.get('noliktava', '')
                ])
            table = Table(table_data, colWidths=[7*cm, 3*cm, 2*cm, 4*cm])
            table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'DejaVuSans'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('PADDING', (0, 0), (-1, -1), 6),
            ]))
            content.append(table)
        else:
            content.append(Paragraph("Nav materiālu datu", styles['Latvian']))
            
    elif report_type == 'workers':
        if data:
            table_data = [['Vārds', 'Uzvārds', 'Amats', 'Statuss']]
            for worker in data:
                table_data.append([
                    worker.get('vards', ''),
                    worker.get('uzvards', ''),
                    worker.get('amats', ''),
                    worker.get('status', '')
                ])
            table = Table(table_data, colWidths=[4*cm, 4*cm, 5*cm, 3*cm])
            table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'DejaVuSans'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('PADDING', (0, 0), (-1, -1), 6),
            ]))
            content.append(table)
        else:
            content.append(Paragraph("Nav darbinieku datu", styles['Latvian']))
            
    elif report_type == 'shifts':
        if data:
            table_data = [['Vārds', 'Uzvārds', 'Amats', 'Stundas']]
            for shift in data:
                table_data.append([
                    shift.get('vards', ''),
                    shift.get('uzvards', ''),
                    shift.get('amats', ''),
                    str(shift.get('hours', ''))
                ])
            table = Table(table_data, colWidths=[4*cm, 4*cm, 5*cm, 3*cm])
            table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), 'DejaVuSans'),
                ('FONTSIZE', (0, 0), (-1, -1), 10),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('PADDING', (0, 0), (-1, -1), 6),
            ]))
            content.append(table)
        else:
            content.append(Paragraph("Nav maiņu datu", styles['Latvian']))
    
    doc.build(content)
    buffer.seek(0)
    return buffer

@app.route('/api/export_pdf', methods=['OPTIONS'])
def export_pdf_options():
    response = jsonify({'message': 'CORS preflight'})
    response.headers.add('Access-Control-Allow-Origin', 'https://kv-darbs.vercel.app')
    response.headers.add('Access-Control-Allow-Headers', 'Authorization, Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
    return response, 200

@app.route('/api/export_pdf', methods=['GET'])
@token_required
def export_pdf(current_user):
    try:
        report_type = request.args.get('type', 'shifts')
        sort_by = request.args.get('sort_by')
        sort_order = request.args.get('sort_order', 'asc')
        search = request.args.get('search', '').lower()
        
        if not sort_by:
            if report_type == 'orders':
                sort_by = 'nosaukums'
            elif report_type == 'materials':
                sort_by = 'nosaukums'
            elif report_type == 'workers':
                sort_by = 'vards'
            elif report_type == 'shifts':
                sort_by = 'vards'
            else:
                sort_by = None
        
        data = []
        try:
            if report_type == 'orders':
                # Iegūstam pasūtījumus
                orders = Order.query.all()
                data = [{
                    'nosaukums': order.nosaukums,
                    'daudzums': order.daudzums,
                    'status': order.status
                } for order in orders]
                
                # Filtrējam pēc meklēšanas
                if search:
                    data = [x for x in data if search in x['nosaukums'].lower()]
                
            elif report_type == 'materials':
                # Iegūstam materiālus
                materials = Material.query.all()
                data = [{
                    'nosaukums': material.nosaukums,
                    'daudzums': material.daudzums,
                    'vieniba': material.vieniba,
                    'noliktava': material.noliktava
                } for material in materials]
                
                # Filtrējam pēc meklēšanas
                if search:
                    data = [x for x in data if search in x['nosaukums'].lower()]
                
            elif report_type == 'workers':
                # Iegūstam darbiniekus
                employees = Employee.query.all()
                data = [{
                    'vards': emp.vards,
                    'uzvards': emp.uzvards,
                    'amats': emp.amats,
                    'status': emp.status
                } for emp in employees]
                
                # Filtrējam pēc meklēšanas
                if search:
                    data = [x for x in data if search in f"{x['vards']} {x['uzvards']}".lower()]
                
            elif report_type == 'shifts':
                # Iegūstam maiņu datus
                start = request.args.get('start_date')
                end = request.args.get('end_date')
                start_date = parser.parse(start) if start else None
                end_date = parser.parse(end) if end else None
                
                employees = Employee.query.options(joinedload(Employee.shifts)).all()
                data = []
                for emp in employees:
                    total_hours = 0
                    for shift in emp.shifts:
                        if not shift.start_time or not shift.end_time:
                            continue
                        if start_date and shift.start_time < start_date:
                            continue
                        if end_date and shift.end_time > end_date:
                            continue
                        duration_hours = (shift.end_time - shift.start_time).total_seconds() / 3600
                        total_hours += duration_hours
                    if total_hours > 0:
                        data.append({
                            'vards': emp.vards,
                            'uzvards': emp.uzvards,
                            'amats': emp.amats,
                            'hours': round(total_hours, 2)
                        })
                
                # Filtrējam pēc meklēšanas
                if search:
                    data = [x for x in data if search in f"{x['vards']} {x['uzvards']}".lower()]
            
            # Kārtojam datus
            if sort_by and data:
                reverse = sort_order == 'desc'
                data.sort(key=lambda x: x.get(sort_by, ''), reverse=reverse)
                
        except Exception as e:
            logging.error(f"Error fetching data: {str(e)}")
            return jsonify({'error': 'Neizdevās iegūt datus'}), 500
        
        try:
            buffer = create_pdf_content(report_type, data)
        except Exception as e:
            logging.error(f"Error generating PDF: {str(e)}")
            return jsonify({'error': 'Neizdevās ģenerēt PDF'}), 500
        
        return send_file(
            buffer,
            as_attachment=True,
            download_name=f"{report_type}_atskaite.pdf",
            mimetype='application/pdf'
        )
        
    except Exception as e:
        logging.error(f"Error in export_pdf: {str(e)}")
        return jsonify({'error': 'Servera kļūda'}), 500
@app.route('/materials/transfer', methods=['POST'])
@token_required
def transfer_material(current_user):
    data = request.get_json()
    material_id = data.get('material_id')
    try:
        amount_str = str(data.get('daudzums', 0)).replace(',', '.')
        amount = float(amount_str)
    except (ValueError, TypeError):
        return jsonify({'error': 'Daudzumam jābūt skaitlim'}), 400
    from_noliktava = data.get('from_noliktava')
    to_noliktava = data.get('to_noliktava')

    if not material_id or not from_noliktava or not to_noliktava or amount < 0.01:
        return jsonify({'error': 'Nepieciešamie lauki nav aizpildīti vai daudzums ir pārāk mazs'}), 400

    
    material_from = Material.query.filter_by(id=material_id, noliktava=from_noliktava).first()
    if not material_from or material_from.daudzums < amount:
        return jsonify({'error': 'Avota noliktavā nav pietiekami daudz materiāla'}), 400

    
    material_to = Material.query.filter_by(nosaukums=material_from.nosaukums, noliktava=to_noliktava).first()
    if material_to:
        material_to.daudzums += amount
    else:
        material_to = Material(
            nosaukums=material_from.nosaukums,
            noliktava=to_noliktava,
            vieta=material_from.vieta,
            vieniba=material_from.vieniba,
            daudzums=amount
        )
        db.session.add(material_to)

    
    material_from.daudzums -= amount
    db.session.commit()

    return jsonify({'success': True, 'message': 'Materiāls pārvietots veiksmīgi'}), 200

@app.route("/orders/<int:order_id>/cancel", methods=["PATCH"])
@token_required
def cancel_order(current_user, order_id):
    try:
        order = Order.query.get(order_id)
        if not order:
            return jsonify({'error': 'Pasūtījums nav atrasts'}), 404

        if order.status == 'finished':
            return jsonify({'error': 'Pabeigtu pasūtījumu nevar atcelt'}), 400

        # Pārbaudam materiālu versijas
        for order_material in order.materials:
            material = Material.query.get(order_material.material_id)
            if not material:
                return jsonify({'error': f'Materiāls ar ID {order_material.material_id} nav atrasts'}), 404
            
            # Pārbaudam versiju
            if material.version != order_material.material_version:
                return jsonify({
                    'error': f'Materiāla "{material.nosaukums}" dati ir mainījušies. Lūdzu, atsvaidziniet lapu un mēģiniet vēlreiz.'
                }), 409

        # Atgriežam materiālu daudzumus
        for order_material in order.materials:
            material = Material.query.get(order_material.material_id)
            if material:
                material.daudzums += order_material.quantity
                material.version += 1

        # Atjauninām pasūtījuma statusu
        order.status = 'cancelled'
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Pasūtījums atcelts",
            "order_id": order.id
        }), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error cancelling order: {str(e)}")
        return jsonify({"error": "Neizdevās atcelt pasūtījumu", "details": str(e)}), 500

@app.route("/materials/<int:material_id>/move", methods=["PATCH"])
@token_required
def move_material(current_user, material_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Nav datu'}), 400

        required_fields = ['noliktava', 'vieta', 'version']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Trūkst lauka: {field}'}), 400

        material = Material.query.get(material_id)
        if not material:
            return jsonify({'error': 'Materiāls nav atrasts'}), 404

        # Pārbaudam versiju
        if material.version != data['version']:
            return jsonify({
                'error': f'Materiāla "{material.nosaukums}" dati ir mainījušies. Lūdzu, atsvaidziniet lapu un mēģiniet vēlreiz.'
            }), 409

        # Atjauninām materiāla atrašanās vietu
        material.noliktava = data['noliktava']
        material.vieta = data['vieta']
        material.version += 1

        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Materiāls pārvietots",
            "material": {
                'id': material.id,
                'nosaukums': material.nosaukums,
                'noliktava': material.noliktava,
                'vieta': material.vieta,
                'vieniba': material.vieniba,
                'daudzums': material.daudzums,
                'version': material.version
            }
        }), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error moving material: {str(e)}")
        return jsonify({"error": "Neizdevās pārvietot materiālu", "details": str(e)}), 500

@app.route("/materials/<int:material_id>/quantity", methods=["PATCH"])
@token_required
def update_material_quantity(current_user, material_id):
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Nav datu'}), 400

        required_fields = ['daudzums', 'version']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'Trūkst lauka: {field}'}), 400

        material = Material.query.get(material_id)
        if not material:
            return jsonify({'error': 'Materiāls nav atrasts'}), 404

        # Pārbaudam versiju
        if material.version != data['version']:
            return jsonify({
                'error': f'Materiāla "{material.nosaukums}" dati ir mainījušies. Lūdzu, atsvaidziniet lapu un mēģiniet vēlreiz.'
            }), 409

        # Pārbaudam daudzumu
        if float(data['daudzums']) < 0.01:
            return jsonify({'error': 'Daudzumam jābūt vismaz 0.01'}), 400

        # Atjauninām materiāla daudzumu
        material.daudzums = float(data['daudzums'])
        material.version += 1

        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Materiāla daudzums atjaunināts",
            "material": {
                'id': material.id,
                'nosaukums': material.nosaukums,
                'noliktava': material.noliktava,
                'vieta': material.vieta,
                'vieniba': material.vieniba,
                'daudzums': material.daudzums,
                'version': material.version
            }
        }), 200

    except Exception as e:
        db.session.rollback()
        logging.error(f"Error updating material quantity: {str(e)}")
        return jsonify({"error": "Neizdevās atjaunināt materiāla daudzumu", "details": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)


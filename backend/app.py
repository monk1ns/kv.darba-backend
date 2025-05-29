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


CORS(app, resources={r"/*": {"origins": "http://localhost:3000"}}, supports_credentials=True)


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
    response.headers.add('Access-Control-Allow-Origin', 'http://localhost:3000')
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
        response.headers.add('Access-Control-Allow-Origin', 'http://localhost:3000')
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

        # Try to convert kods to integer if it's a string
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

        # Try to convert kods to integer if it's a string
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
        materials_list = [{
            "id": material.id,
            "nosaukums": material.nosaukums,
            "noliktava": material.noliktava,
            'daudzums': material.daudzums,
            "vieta": material.vieta,
            "vieniba": material.vieniba
        } for material in materials]
        return jsonify({"success": True, "materials": materials_list}), 200
    except Exception as e:
        logging.error(f"Error fetching materials: {str(e)}")
        return jsonify({"error": "Failed to fetch materials", "details": str(e)}), 500
@app.route("/materials/<int:material_id>", methods=["GET"])
@token_required
def get_material_by_id(current_user, material_id):
    try:
        material = db.session.get(Material, material_id)

        if not material:
            return jsonify({"error": "Materiāls nav atrasts"}), 404

        material_data = {
            "id": material.id,
            "nosaukums": material.nosaukums,
            "noliktava": material.noliktava,
            "vieta": material.vieta,
            "daudzums":material.daudzums,
            "vieniba": material.vieniba,
        }

        return jsonify(material_data), 200

    except Exception as e:
        logging.error(f"Kļūda saņemot materiālu pēc ID: {str(e)}")
        return jsonify({"error": "Kļūda serverī", "details": str(e)}), 500




@app.route("/orders", methods=["GET"])
@token_required
def get_orders(current_user):
    try:
        orders = Order.query.all()
        result = []
        for order in orders:
            result.append({
                "id": order.id,
                "nosaukums": order.nosaukums,
                "daudzums": order.daudzums,
                "status": order.status,
                "materials": [
                    {
                        "material_id": m.material_id,
                        "daudzums": m.daudzums,
                        "material_name": m.material.nosaukums,
                        "vieniba": m.material.vieniba
                    }
                    for m in order.materials
                ],
                "employee": {
                    "vards": order.employee.vards,
                    "uzvards": order.employee.uzvards
                } if order.employee else None
            })
        return jsonify(result), 200
    except Exception as e:
        logging.error(f"Kļūda saņemot pasūtījumus: {str(e)}")
        return jsonify({"error": "Neizdevās iegūt pasūtījumus"}), 500


@app.route("/orders/<int:order_id>", methods=["GET"])
@token_required
def get_order_by_id(current_user, order_id):
    try:
        order = Order.query.get(order_id)
        if not order:
            return jsonify({"error": "Pasūtījums nav atrasts"}), 404

        materials = []
        for order_material in order.materials:
            material_data = {
                "material_id": order_material.material.id,
                "material_name": order_material.material.nosaukums,
                "quantity": float(order_material.daudzums),
                "daudzums": float(order_material.daudzums),
            }
            materials.append(material_data)

        response_data = {
            "id": order.id,
            "nosaukums": order.nosaukums,
            "daudzums": order.daudzums,
            "status": order.status,
            "materials": [
                {
                    "material_id": m.material_id,
                    "daudzums": float(m.daudzums),
                    "material_name": m.material.nosaukums,
                    "vieniba": m.material.vieniba
                }
                for m in order.materials
            ],
            "employee": {
                "id": order.employee.id if order.employee else None,
                "vards": order.employee.vards if order.employee else None,
                "uzvards": order.employee.uzvards if order.employee else None
            } if order.employee else None,
            "materials": materials
        }

        return jsonify(response_data), 200

    except Exception as e:
        logging.error(f"Kļūda saņemot pasūtījumu pēc ID: {str(e)}")
        return jsonify({"error": "Kļūda serverī", "details": str(e)}), 500

@app.route("/orders/<int:order_id>/accept", methods=["PATCH"])
@token_required
def accept_order(current_user, order_id):
    try:
        order = Order.query.get(order_id)
        if not order:
            return jsonify({"error": "Pasūtījums nav atrasts"}), 404
        if order.status == "Pabeigts":
            return jsonify({"error": "Pasūtījums jau ir pabeigts"}), 400
        if order.employee_id is not None:
            return jsonify({"error": "Pasūtījums jau ir piešķirts darbiniekam"}), 400

        
        for order_material in order.materials:
            required_qty = order_material.daudzums * order.daudzums
            material = Material.query.get(order_material.material_id)

            if material.daudzums < required_qty:
                return jsonify({
                    "error": f"Nepietiek materiāla: {material.nosaukums}, nepieciešams {required_qty}, ir tikai {material.daudzums}"
                }), 400

            material.daudzums -= required_qty

        
        order.employee_id = current_user.id
        order.status = "Pieņemts"
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Pasūtījums pieņemts un materiāli nomainīti",
            "order": {
                "id": order.id,
                "nosaukums": order.nosaukums,
                "employee": {"vards": current_user.vards, "uzvards": current_user.uzvards}
            }
        }), 200

    except Exception as e:
        logging.error(f"Error accepting order: {str(e)}")
        return jsonify({"error": "Kļūda serverī", "details": str(e)}), 500

@app.route('/orders/<int:order_id>/finish', methods=['PATCH'])
@token_required
def finish_order(current_user, order_id):
    try:
        order = Order.query.get(order_id)
        if not order:
            return jsonify({"error": "Pasūtījums nav atrasts"}), 404
        if order.status == "Pabeigts":
            return jsonify({"error": "Pasūtījums jau ir pabeigts"}), 400
        if order.status != "Pieņemts":
            return jsonify({"error": "Pasūtījums vēl nav pieņemts"}), 400
        if order.employee_id != current_user.id:
            return jsonify({"error": "Jūs nevarat pabeigt šo pasūtījumu, jo tas nav piešķirts Jums"}), 403
        
        order.status = "Pabeigts"
        db.session.commit()
        return jsonify({
            "success": True,
            "message": "Pasūtījums pabeigts",
            "order": {
                "id": order.id,
                "nosaukums": order.nosaukums,
                "status": order.status,
                "employee": {"vards": current_user.vards, "uzvards": current_user.uzvards}
            }
        }), 200
    except Exception as e:
        logging.error(f"Error finishing order: {str(e)}")
        return jsonify({"error": "Kļūda serverī", "details": str(e)}), 500

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
        
        # Handle password update if provided
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
        order = db.session.get(Order, order_id)
        if not order:
            return jsonify({"error": "Pasūtījums nav atrasts"}), 404

        data = request.get_json()
        logging.debug(f"Received data for order update: {data}")

        # Pamata lauku atjaunošana
        order.nosaukums = data.get("nosaukums", order.nosaukums)
        order.daudzums = data.get("daudzums", order.daudzums)
        order.status = data.get("status", order.status)

        # Materiālu apstrāde
        if "materials" in data:
            materials = data["materials"]

            # Validējam, ka visi ieraksti ir korekti
            for mat in materials:
                if not isinstance(mat, dict):
                    return jsonify({"error": "Katrai materiāla vienībai jābūt objektam"}), 400

                missing_keys = [key for key in ["material_id", "daudzums"] if key not in mat]
                if missing_keys:
                    return jsonify({
                        "error": f"Nepareizs materiālu formāts: materiālam ar ID {mat.get('material_id', 'nezināms')} trūkst {', '.join(missing_keys)}"
                    }), 400

                if float(mat["daudzums"]) < 0.01:
                    return jsonify({
                        "error": f"Materiāla daudzumam jābūt vismaz 0.01"
                    }), 400

                material = db.session.get(Material, mat["material_id"])
                if not material:
                    return jsonify({
                        "error": f"Materiāls ar ID {mat['material_id']} nav atrasts"
                    }), 404

            # Pārbaudām vai pietiek materiālu jaunajam pasūtījumam
            for mat in materials:
                material = db.session.get(Material, mat["material_id"])
                total_needed = float(data["daudzums"]) * float(mat["daudzums"])
                if material.daudzums < total_needed:
                    return jsonify({
                        "error": f"Nepietiek materiāla: {material.nosaukums}, nepieciešams {total_needed}, ir tikai {material.daudzums}"
                    }), 400

            # Izdzēšam vecos materiālus un ievietojam jaunus
            OrderMaterial.query.filter_by(order_id=order.id).delete()
            for mat in materials:
                new_mat = OrderMaterial(
                    order_id=order.id,
                    material_id=mat["material_id"],
                    daudzums=mat["daudzums"]
                )
                db.session.add(new_mat)

        db.session.commit()
        return jsonify({"success": True, "message": "Pasūtījums atjaunināts"}), 200

    except Exception as e:
        logging.exception("Update order error")
        return jsonify({
            "error": "Neizdevās atjaunināt pasūtījumu",
            "details": str(e)
        }), 500
@app.route("/materials", methods=["POST"])
@token_required
def create_material(current_user):
    try:
        data = request.get_json()
        if not data or not all(k in data for k in ['nosaukums', 'noliktava', 'vieta', 'vieniba', 'daudzums']):
            return jsonify({'error': 'Trūkst nepieciešamie lauki'}), 400
        try:
            daudzums_str = str(data['daudzums']).replace(',', '.')
            daudzums = float(daudzums_str)
        except (ValueError, TypeError):
            return jsonify({'error': 'Daudzumam jābūt skaitlim'}), 400
        if daudzums < 0.01:
            return jsonify({'error': 'Daudzumam jābūt vismaz 0.01'}), 400

        # Pārbaude, vai jau eksistē materiāls ar tādu pašu nosaukumu un noliktavu
        existing_material = Material.query.filter_by(
            nosaukums=data['nosaukums'],
            noliktava=data['noliktava']
        ).first()

        if existing_material:
            existing_material.daudzums += daudzums
            db.session.commit()
            return jsonify({
                'id': existing_material.id,
                'nosaukums': existing_material.nosaukums,
                'noliktava': existing_material.noliktava,
                'vieta': existing_material.vieta,
                'vieniba': existing_material.vieniba,
                'daudzums': existing_material.daudzums
            }), 200

        material = Material(
            nosaukums=data['nosaukums'],
            noliktava=data['noliktava'],
            vieta=data['vieta'],
            vieniba=data['vieniba'],
            daudzums=daudzums
        )
        db.session.add(material)
        db.session.commit()
        return jsonify({
            'id': material.id,
            'nosaukums': material.nosaukums,
            'noliktava': material.noliktava,
            'vieta': material.vieta,
            'vieniba': material.vieniba,
            'daudzums': material.daudzums
        }), 201
    except Exception as e:
        logging.error(f"Error creating material: {str(e)}")
        return jsonify({"error": "Failed to create material", "details": str(e)}), 500

@app.route("/materials/<int:material_id>", methods=["PUT"])
@token_required
def update_material(current_user, material_id):
    try:
        material = Material.query.get(material_id)
        if not material:
            return jsonify({"error": "Materiāls nav atrasts"}), 404
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Nav datu'}), 400
        
        if 'daudzums' in data:
            if float(data['daudzums']) < 0.01:
                return jsonify({'error': 'Daudzumam jābūt vismaz 0.01'}), 400
            material.daudzums = float(data['daudzums'])
        
        if 'nosaukums' in data:
            material.nosaukums = data['nosaukums']
        if 'noliktava' in data:
            material.noliktava = data['noliktava']
        if 'vieta' in data:
            material.vieta = data['vieta']
        if 'vieniba' in data:
            material.vieniba = data['vieniba']
        
        db.session.commit()
        return jsonify({
            'id': material.id,
            'nosaukums': material.nosaukums,
            'noliktava': material.noliktava,
            'vieta': material.vieta,
            'vieniba': material.vieniba,
            'daudzums': material.daudzums
        }), 200
    except Exception as e:
        logging.error(f"Error updating material: {str(e)}")
        return jsonify({"error": "Failed to update material", "details": str(e)}), 500

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

@app.route('/orders', methods=['POST'])
@token_required
def create_order(current_user):
    data = request.get_json()
    try:
        if not data or not all(k in data for k in ['nosaukums', 'daudzums', 'materials']):
            return jsonify({'error': 'Trūkst nepieciešamie lauki'}), 400
        
        if float(data['daudzums']) < 0.01:
            return jsonify({'error': 'Daudzumam jābūt vismaz 0.01'}), 400
        
        order = Order(
            nosaukums=data['nosaukums'],
            daudzums=float(data['daudzums']),
            employee_id=data.get('employee_id')
        )
        db.session.add(order)
        db.session.flush()  

        materials = data['materials']
        for material_data in materials:
            if float(material_data['daudzums']) < 0.01:
                return jsonify({'error': 'Materiāla daudzumam jābūt vismaz 0.01'}), 400
            
            material = Material.query.get(material_data['id'])
            if not material:
                return jsonify({'error': f'Materiāls ar ID {material_data["id"]} nav atrasts'}), 404
            
            # Check if enough material is available for the whole order
            total_needed = float(data['daudzums']) * float(material_data['daudzums'])
            if material.daudzums < total_needed:
                return jsonify({'error': f"Nepietiek materiāla: {material.nosaukums}, nepieciešams {total_needed}, ir tikai {material.daudzums}"}), 400
            
            order_material = OrderMaterial(
                order_id=order.id,
                material_id=material.id,
                daudzums=float(material_data['daudzums'])
            )
            db.session.add(order_material)
            # material.daudzums -= total_needed  # REMOVE THIS LINE

        db.session.commit()

        return jsonify({
            'id': order.id,
            'nosaukums': order.nosaukums,
            'daudzums': order.daudzums,
            'employee_id': order.employee_id,
            'status': order.status,
            'materials': [{
                'id': om.material.id,
                'nosaukums': om.material.nosaukums,
                'daudzums': om.daudzums
            } for om in order.materials]
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@app.route("/orders/<int:order_id>", methods=["DELETE"])
@token_required
def delete_order(current_user, order_id):
    try:
        order = Order.query.get(order_id)
        if not order:
            return jsonify({"error": "Pasūtījums nav atrasts"}), 404

        db.session.delete(order)
        db.session.commit()
        return jsonify({"success": True, "message": "Pasūtījums izdzēsts"}), 200
    except Exception as e:
        logging.error(f"Error deleting order: {str(e)}")
        return jsonify({"error": "Failed to delete order", "details": str(e)}), 500
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

    # Register DejaVuSans font for Latvian characters
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
    
    # Add title based on report type
    titles = {
        'orders': 'Pasūtījumu Atskaite',
        'materials': 'Materiālu Atskaite',
        'workers': 'Darbinieku Atskaite',
        'shifts': 'Maiņu Atskaite'
    }
    
    content.append(Paragraph(titles.get(report_type, 'Atskaite'), styles['LatvianTitle']))
    content.append(Spacer(1, 20))
    
    # Add content based on report type
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
    response.headers.add('Access-Control-Allow-Origin', 'http://localhost:3000')
    response.headers.add('Access-Control-Allow-Headers', 'Authorization, Content-Type')
    response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
    return response, 200

@app.route('/api/export_pdf', methods=['GET'])
@token_required
def export_pdf(current_user):
    try:
        report_type = request.args.get('type', 'shifts')
        sort_by = request.args.get('sort_by')
        sort_order = request.args.get('sort_order', 'asc')  # Default ascending order
        
        # Set default sort_by for each report type
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
        
        # Get data based on report type
        data = []
        try:
            if report_type == 'orders':
                orders = Order.query.all()
                data = [{
                    'nosaukums': order.nosaukums,
                    'daudzums': order.daudzums,
                    'status': order.status
                } for order in orders]
                # Sort orders if field exists
                if sort_by and all(sort_by in x for x in data):
                    data.sort(key=lambda x: x[sort_by], reverse=(sort_order == 'desc'))
            elif report_type == 'materials':
                materials = Material.query.all()
                data = [{
                    'nosaukums': material.nosaukums,
                    'daudzums': material.daudzums,
                    'vieniba': material.vieniba,
                    'noliktava': material.noliktava
                } for material in materials]
                if sort_by and all(sort_by in x for x in data):
                    data.sort(key=lambda x: x[sort_by], reverse=(sort_order == 'desc'))
            elif report_type == 'workers':
                employees = Employee.query.all()
                data = [{
                    'vards': emp.vards,
                    'uzvards': emp.uzvards,
                    'amats': emp.amats,
                    'status': emp.status
                } for emp in employees]
                if sort_by and all(sort_by in x for x in data):
                    data.sort(key=lambda x: x[sort_by], reverse=(sort_order == 'desc'))
            elif report_type == 'shifts':
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
                if sort_by and all(sort_by in x for x in data):
                    data.sort(key=lambda x: x[sort_by], reverse=(sort_order == 'desc'))
            else:
                return jsonify({'error': 'Nederīgs atskaites veids'}), 400
                
        except Exception as e:
            logging.error(f"Error fetching data: {str(e)}")
            return jsonify({'error': 'Neizdevās iegūt datus'}), 500
        
        # Generate PDF
        try:
            buffer = create_pdf_content(report_type, data)
        except Exception as e:
            logging.error(f"Error generating PDF: {str(e)}")
            return jsonify({'error': 'Neizdevās ģenerēt PDF'}), 500
        
        # Return the PDF file
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

    # Atrodi materiālu avota noliktavā
    material_from = Material.query.filter_by(id=material_id, noliktava=from_noliktava).first()
    if not material_from or material_from.daudzums < amount:
        return jsonify({'error': 'Avota noliktavā nav pietiekami daudz materiāla'}), 400

    # Atrodi vai izveido materiālu mērķa noliktavā
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

    # Samazini daudzumu avota noliktavā
    material_from.daudzums -= amount
    db.session.commit()

    return jsonify({'success': True, 'message': 'Materiāls pārvietots veiksmīgi'}), 200

if __name__ == "__main__":
    app.run(debug=True)


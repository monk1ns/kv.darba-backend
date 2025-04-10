from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship
import jwt
import datetime
from functools import wraps
import logging

# Flask app setup
app = Flask(__name__)

# CORS setup for frontend on port 3000
CORS(app, resources={r"/*": {"origins": "http://localhost:3000"}}, supports_credentials=True)

# PostgreSQL connection string
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:111@localhost:5432/kvdarbs'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# JWT secret key
SECRET_KEY = "your_secret_key"

# Logging setup
logging.basicConfig(level=logging.DEBUG)

# --- Models ---

class Employee(db.Model):
    __tablename__ = 'employees'
    id = db.Column(db.Integer, primary_key=True)
    vards = db.Column(db.String(15))
    uzvards = db.Column(db.String(15))
    amats = db.Column(db.String(20))
    kods = db.Column(db.Integer)
    status = db.Column(db.String(10))
    token = db.Column(db.String(512))

    shifts = db.relationship("Shift", backref="employee")
    orders = db.relationship("Order", backref="employee")


class Shift(db.Model):
    __tablename__ = 'shifts'
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'))
    start_time = db.Column(db.DateTime(timezone=True))
    end_time = db.Column(db.DateTime(timezone=True))
    status = db.Column(db.String(20))


class Material(db.Model):
    __tablename__ = 'materials'
    id = db.Column(db.Integer, primary_key=True)
    nosaukums = db.Column(db.String(50))
    noliktava = db.Column(db.String(20))
    vieta = db.Column(db.String(20))
    vieniba = db.Column(db.String(20))
    daudzums = db.Column(db.INTEGER)

    order_links = db.relationship("OrderMaterial", backref="material")


class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.Integer, primary_key=True)
    nosaukums = db.Column(db.String(50))
    daudzums = db.Column(db.Integer)
    employee_id = db.Column(db.Integer, db.ForeignKey('employees.id'), nullable=True)
    status = db.Column(db.String(20), default="Nav sākts")      
   
    materials = db.relationship("OrderMaterial", backref="order")



class OrderMaterial(db.Model):
    __tablename__ = 'order_materials'
    order_id = db.Column(db.Integer, db.ForeignKey('orders.id'), primary_key=True)
    material_id = db.Column(db.Integer, db.ForeignKey('materials.id'), primary_key=True)
    daudzums = db.Column(db.Integer)


# --- Helper functions ---

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


# --- Routes ---

@app.route("/login", methods=["POST"])
def login():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON body received"}), 400

        kods = data.get("kods")
        if not kods:
            return jsonify({"error": "Kods not provided"}), 400

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
            "redirect": "/adminpanel" if user.amats == "Administrators" else "/home"
        }), 200

    except Exception as e:
        logging.exception("Login error:")
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
        material = Material.query.get(material_id)
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
        # Fetch the order by its ID
        order = Order.query.get(order_id)
        if not order:
            return jsonify({"error": "Pasūtījums nav atrasts"}), 404
        
        # Collect materials information associated with the order
        materials = []
        for order_material in order.materials:
            material_data = {
                "material_name": order_material.material.nosaukums,
                "quantity": order_material.daudzums,
                
            }
            materials.append(material_data)
        
        # Prepare the response with order details
        response_data = {
            "id": order.id,
            "nosaukums": order.nosaukums,
            "daudzums": order.daudzums,
            "status": order.status,
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

        # Проверка и списание материалов
        for order_material in order.materials:
            required_qty = order_material.daudzums * order.daudzums
            material = Material.query.get(order_material.material_id)

            if material.daudzums < required_qty:
                return jsonify({
                    "error": f"Nepietiek materiāla: {material.nosaukums}, nepieciešams {required_qty}, ir tikai {material.daudzums}"
                }), 400

            material.daudzums -= required_qty

        # Привязка сотрудника и обновление статуса
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
        # Изменить статус заказа на "Pabeigts"
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
        new_employee = Employee(
            vards=data["vards"],
            uzvards=data["uzvards"],
            amats=data["amats"],
            kods=data["kods"],
            status=data["status"]
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



@app.route("/materials", methods=["POST"])
@token_required
def create_material(current_user):
    try:
        data = request.get_json()
        new_material = Material(
            nosaukums=data['nosaukums'],
            noliktava=data['noliktava'],
            vieta=data.get('vieta', ''), 
            vieniba=data.get('vieniba', ''),
            daudzums=data['daudzums']
        )
        db.session.add(new_material)
        db.session.commit()
        return jsonify({"success": True, "message": "Materiāls pievienots"}), 201
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
        material.nosaukums = data.get('nosaukums', material.nosaukums)
        material.noliktava = data.get('noliktava', material.noliktava)
        material.vieta = data.get('vieta', material.vieta)  # Обновление поля "vieta"
        material.vieniba = data.get('vieniba', material.vieniba)
        material.daudzums = data.get('daudzums', material.daudzums)
        db.session.commit()
        return jsonify({"success": True, "message": "Materiāls atjaunināts"}), 200
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
# --- Run app ---
if __name__ == "__main__":
    app.run(debug=True)

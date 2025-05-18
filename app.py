from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship
from sqlalchemy.orm import joinedload
import jwt
import datetime
from functools import wraps
import bcrypt
import logging

# Flask app setup
app = Flask(__name__)

# CORS setup for frontend on port 3000
CORS(app, resources={r"/*": {"origins": "http://localhost:3001"}}, supports_credentials=True)

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
@app.route("/api/stats/materials", methods=["GET"])
def get_material_stats():
    try:
        results = db.session.query(
            UsedMaterial.name,
            db.func.sum(UsedMaterial.quantity).label("total")
        ).group_by(UsedMaterial.name).all()

        data = [{"name": name, "total": total} for name, total in results]
        return jsonify(data), 200
    except Exception as e:
        print("Error:", e)
        return jsonify({"error": "Neizdevās iegūt statistiku"}), 500



@app.route("/login", methods=["POST"])
def login():
    try:
        data = request.get_json()
        print("Received data:", data)  # Логируем входящие данные
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
        print("Error during login:", str(e))
        return jsonify({"error": "Server error"}), 500

@app.route("/login/password", methods=["POST"])
def login_with_password():
    try:
        # Получение данных из запроса
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON body received"}), 400

        kods = data.get("kods")
        password = data.get("password")
        
        if not kods or not password:
            return jsonify({"error": "Kods or password not provided"}), 400

        # Поиск пользователя по коду
        user = Employee.query.filter_by(kods=kods).first()
        if not user:
            return jsonify({"error": "User not found"}), 404

        # Проверка пароля с использованием bcrypt
        if not bcrypt.checkpw(password.encode('utf-8'), user.password.encode('utf-8')):
            return jsonify({"error": "Incorrect password"}), 401

        # Генерация токена для пользователя
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
            "redirect": "/adminpanel" if user.amats == "Administrators" else "/home"
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
@app.route('/orders', methods=['POST'])
@token_required
def create_order(current_user):
    data = request.json
    try:
        # Создаём заказ
        order = Order(
            nosaukums=data['nosaukums'],
            daudzums=data['daudzums'],
            status=data.get('status', 'Nav sākts')
        )
        db.session.add(order)
        db.session.flush()  # Получаем order.id до коммита

        # Обработка материалов
        materials = data.get('materials', [])
        for material in materials:
            material_id = material['material_id']
            quantity = material['quantity']

            db_material = Material.query.get(material_id)
            if not db_material:
                return jsonify({'error': f'Materiāls ar ID {material_id} nav atrasts'}), 404
            if db_material.daudzums < quantity:
                return jsonify({'error': f'Nepietiek materiāla: {db_material.nosaukums}'}), 400

            order_material = OrderMaterial(
                order_id=order.id,
                material_id=material_id,
                quantity=quantity
            )
            db.session.add(order_material)
            db_material.daudzums -= quantity

        db.session.commit()

        return jsonify({
            'id': order.id,
            'nosaukums': order.nosaukums,
            'daudzums': order.daudzums,
            'status': order.status
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
        # Проверяем наличие активной смены через end_time
        active_shift = Shift.query.filter(
            Shift.employee_id == current_user.id,
            Shift.end_time.is_(None)  # Активная смена = end_time не установлен
        ).first()

        if active_shift:
            return jsonify({"error": "Jums jau ir aktīva maiņa."}), 400

        # Создаем новую смену
        new_shift = Shift(
            employee_id=current_user.id,
            start_time=datetime.datetime.utcnow(),  # Используем текущее время
            end_time=None  # Явно указываем отсутствие end_time
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

        # Обновляем только end_time
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
    
@app.route('/api/work_stats', methods=['GET'])
def get_work_stats():
    try:
        employees = Employee.query.options(joinedload(Employee.shifts)).all()
        stats = []
        for emp in employees:
            total_seconds = sum(
                (shift.end_time - shift.start_time).total_seconds()
                for shift in emp.shifts
                if shift.start_time and shift.end_time
            )
            stats.append({
                "id": emp.id,
                "hours": round(total_seconds / 3600, 2)
            })
        return jsonify(stats), 200
    except Exception as e:
        logging.error(f"Stats error: {str(e)}")
        return jsonify({"error": "Stats generation failed"}), 500

@app.route('/api/employees/stats', methods=['GET'])
def get_employees_with_stats():
    try:
        employees = Employee.query.options(joinedload(Employee.shifts)).all()
        result = []
        for emp in employees:
            total_seconds = sum(
                (shift.end_time - shift.start_time).total_seconds()
                for shift in emp.shifts
                if shift.start_time and shift.end_time
            )
            result.append({
                **emp.serialize(),
                "hours": round(total_seconds / 3600, 2)
            })
        return jsonify(result), 200
    except Exception as e:
        logging.error(f"Employees stats error: {str(e)}")
        return jsonify({"error": "Server error"}), 500
        
@app.route('/api/shifts/stats', methods=['GET', 'OPTIONS'])
def get_shifts_stats():
    if request.method == 'OPTIONS':
        # Предоставить корректный CORS preflight ответ
        response = jsonify({'message': 'CORS preflight'})
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Authorization, Content-Type')
        response.headers.add('Access-Control-Allow-Methods', 'GET, OPTIONS')
        return response, 200

    try:
        employees = Employee.query.options(joinedload(Employee.shifts)).all()
        stats = []
        for emp in employees:
            total_seconds = sum(
                (shift.end_time - shift.start_time).total_seconds()
                for shift in emp.shifts
                if shift.start_time and shift.end_time
            )
            stats.append({
                "id": emp.id,
                "vards": emp.vards,
                "uzvards": emp.uzvards,
                "amats": emp.amats,
                "hours": round(total_seconds / 3600, 2)
            })
        response = jsonify(stats)
        response.headers.add('Access-Control-Allow-Origin', '*')
        return response, 200
    except Exception as e:
        logging.error(f"Stats error: {str(e)}")
        return jsonify({"error": "Stats generation failed"}), 500

@app.route('/api/export_pdf', methods=['GET'])
def export_pdf():
    try:
        employees = Employee.query.options(joinedload(Employee.shifts)).all()
        buffer = io.BytesIO()
        c = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        
        # Header
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, height-50, "Employee Work Hours Report")
        c.setFont("Helvetica", 12)
        y = height - 80
        
        # Content
        for emp in employees:
            total_seconds = sum(
                (shift.end_time - shift.start_time).total_seconds()
                for shift in emp.shifts
                if shift.start_time and shift_end_time
            )
            hours = round(total_seconds / 3600, 2)
            line = f"{emp.vards} {emp.uzvards} ({emp.amats}): {hours} hours"
            c.drawString(50, y, line)
            y -= 20
            if y < 50:
                c.showPage()
                y = height - 50
                c.setFont("Helvetica", 12)
        
        c.save()
        buffer.seek(0)
        return send_file(
            buffer,
            as_attachment=True,
            download_name="work_report.pdf",
            mimetype="application/pdf"
        )
    except Exception as e:
        logging.error(f"PDF error: {str(e)}")
        return jsonify({"error": "PDF generation failed"}), 500

if __name__ == "__main__":
    app.run(debug=True)

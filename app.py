import jwt
import datetime
from flask import Flask, jsonify, request
from flask_cors import CORS
from pymongo import MongoClient
from bson.json_util import dumps
from bson.objectid import ObjectId
from flask import Flask, jsonify
from bson.errors import InvalidId
from functools import wraps
import logging

logging.basicConfig(level=logging.DEBUG)

app = Flask(__name__)
CORS(app)

# Подключение к MongoDB
client = MongoClient("mongodb://localhost:27017/kvdarbs")
db = client["kvdarbs"]
orders_collection = db.orders
materials_collection = db["materials"]
warehouses_collection = db["warehouses"]
employees_collection = db["employees"]

# Секретный ключ для создания токенов
SECRET_KEY = "your_secret_key"

# Функция для генерации токенов
def generate_token(user_id):
    expiration = datetime.datetime.utcnow() + datetime.timedelta(hours=1)  # Токен действует 1 час
    payload = {
        'user_id': str(user_id),
        'exp': expiration
    }
    token = jwt.encode(payload, SECRET_KEY, algorithm='HS256')
    return token

def token_required(f):
    @wraps(f)
    def decorator(*args, **kwargs):
        token = request.headers.get('Authorization')
        print(f"Received token: {token}")  # Логируем полученный токен

        if not token:
            return jsonify({"error": "Token is missing!"}), 403

        try:
            if token.startswith("Bearer "):
                token = token[7:]  # Убираем "Bearer " из начала
            else:
                return jsonify({"error": "Token format is incorrect!"}), 403

            decoded_token = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
            current_user_id = decoded_token['user_id']
            current_user = employees_collection.find_one({"_id": ObjectId(current_user_id)})
            if not current_user:
                return jsonify({"error": "User not found"}), 404

        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 403

        return f(current_user, *args, **kwargs)
    return decorator

@app.route("/logout", methods=["POST"])
@token_required
def logout(current_user):
    try:
        # Удаляем токен из базы данных
        employees_collection.update_one(
            {"_id": ObjectId(current_user["_id"])},
            {"$unset": {"token": ""}}
        )
        return jsonify({"success": True, "message": "Logout successful"}), 200
    except Exception as e:
        return jsonify({"error": "Failed to log out", "details": str(e)}), 500


@app.route("/login", methods=["POST"])
def login():
    try:
        # Receive the incoming JSON data from the frontend
        data = request.get_json()
        kodas = data.get("kods", "").strip()  # Remove any extra spaces
        print(f"Received kodas from frontend: '{kodas}'")  # Log the received kodas value

        # Check if the kodas exists in the database
        user = employees_collection.find_one({"kods": kodas})
        if user:
            print(f"User found: {user}")  # Log the user if found
            # Generate token for the user
            token = generate_token(user["_id"])
            
            # Save the token in the database (optional)
            employees_collection.update_one({"_id": user["_id"]}, {"$set": {"token": token}})
            
            return jsonify({
                "success": True,
                "message": "Pieteikšanās veiksmīga",
                "token": token,
                "user": {
                    "vards": user.get("vards", ""),
                    "uzvards": user.get("uzvards", ""),
                    "amats": user.get("amats", "")
                },
                "redirect": "/adminpanel" if user.get("amats") == "Administrators" else "/home"
            }), 200
        else:
            print(f"User with kodas '{kodas}' not found in the database.")  # Log when user is not found
            return jsonify({"error": "Nepareizs kods"}), 401
    except Exception as e:
        print(f"Error during login: {str(e)}")
        return jsonify({"error": "Servera kļūda", "details": str(e)}), 500


@app.route("/materials/<material_id>", methods=["GET"])
@token_required
def get_material_by_id(current_user, material_id):
    try:
        # Проверяем, является ли material_id корректным ObjectId
        try:
            obj_id = ObjectId(material_id)
        except InvalidId:
            return jsonify({"error": "Invalid ID format"}), 400

        # Ищем материал по _id
        material = materials_collection.find_one({"_id": obj_id})
        if not material:
            return jsonify({"error": "Material not found"}), 404

        # Преобразуем ObjectId в строки
        material["_id"] = str(material["_id"])

        # Получаем информацию о складе
        warehouse_id = material.get("warehouse_id")
        if warehouse_id:
            try:
                warehouse = warehouses_collection.find_one({"_id": ObjectId(warehouse_id)})
                if warehouse:
                    material["warehouse"] = {
                        "warehouse_id": str(warehouse["_id"]),
                        "warehouse_name": warehouse.get("nosaukums", "Nezināms noliktava"),
                    }
                else:
                    material["warehouse"] = {
                        "warehouse_id": str(warehouse_id),
                        "warehouse_name": "Nezināms noliktava",
                    }
            except InvalidId:
                material["warehouse"] = {
                    "warehouse_id": str(warehouse_id),
                    "warehouse_name": "Nezināms noliktava",
                }
        else:
            material["warehouse"] = {"warehouse_id": None, "warehouse_name": "Nav norādīts"}

        return app.response_class(dumps(material), content_type="application/json"), 200

    except Exception as e:
        print(f"Error fetching material: {str(e)}")
        return jsonify({"error": "Failed to fetch material", "details": str(e)}), 500


@app.route("/materials", methods=["GET"])
@token_required
def get_materials(current_user):
    try:
        materials = list(materials_collection.find())  # Получаем все материалы
        
        # Преобразуем ObjectId в строки
        for material in materials:
            material['_id'] = str(material['_id'])
            if 'warehouse_id' in material and material['warehouse_id']:
                material['warehouse_id'] = str(material['warehouse_id'])
        
        return app.response_class(dumps(materials), content_type="application/json"), 200
    except Exception as e:
        return jsonify({"error": "Failed to fetch materials", "details": str(e)}), 500


@app.route("/orders", methods=["GET"])
@token_required
def get_orders(current_user):
    try:
        # Получаем все заказы из базы данных
        orders = list(orders_collection.find())
        
        # Преобразуем ObjectId в строку для каждого заказа
        for order in orders:
            order['_id'] = str(order['_id'])  # Преобразуем ObjectId в строку
            
            # Преобразуем материалы в строковый ID
            if 'materials' in order:
                for material in order['materials']:
                    material['material_id'] = str(material.get('material_id', ''))
        
        return jsonify(orders), 200
    except Exception as e:
        print(f"Ошибка при получении заказов: {str(e)}")  # Отладочное сообщение
        return jsonify({"error": "Произошла ошибка при загрузке заказов"}), 500


@app.route("/orders/<order_id>", methods=["GET"])
@token_required
def get_order_by_id(current_user, order_id):
    try:
        # Check if the order_id is a valid ObjectId
        try:
            obj_id = ObjectId(order_id)
        except InvalidId:
            return jsonify({"error": "Invalid ID format"}), 400

        # Find the order by _id
        order = orders_collection.find_one({"_id": obj_id})
        if not order:
            return jsonify({"error": "Order not found"}), 404

        # Convert ObjectId to string
        order["_id"] = str(order["_id"])

        # Process materials
        for material in order.get("materials", []):
            mat_id = material.get("material_id")
            if mat_id:
                try:
                    material_doc = materials_collection.find_one({"_id": ObjectId(mat_id)})
                    if material_doc:
                        material["material_name"] = material_doc.get("nosaukums", "Not provided")
                    else:
                        material["material_name"] = "Not found"
                except InvalidId:
                    material["material_name"] = "Error retrieving material"

        # Process worker (if applicable)
        if "darbinieks" in order:
            worker_id = order["darbinieks"].get("worker_id")
            if worker_id:
                worker = employees_collection.find_one({"_id": ObjectId(worker_id)})
                if worker:
                    order["darbinieks"]["worker_name"] = f"{worker.get('first_name', 'Unknown')} {worker.get('last_name', 'Unknown')}"
                else:
                    order["darbinieks"]["worker_name"] = "Unknown worker"

        return app.response_class(dumps(order), content_type="application/json"), 200

    except Exception as e:
        print(f"Error fetching order: {str(e)}")
        return jsonify({"error": "Failed to fetch order", "details": str(e)}), 500



@app.route("/employees", methods=["GET"])
@token_required
def get_employees(current_user):
    try:
        employees = list(employees_collection.find())
        for employee in employees:
            employee["_id"] = str(employee["_id"])  # Преобразуем ObjectId в строку
        return app.response_class(dumps(employees), content_type="application/json"), 200
    except Exception as e:
        logging.error(f"Error fetching employees: {str(e)}")
        return jsonify({"error": "Failed to fetch employees", "details": str(e)}), 500

# Маршрут для добавления нового сотрудника
@app.route("/employees", methods=["POST"])
@token_required
def add_employee(current_user):
    try:
        data = request.get_json()

        # Проверка обязательных полей
        if not data.get("vards") or not data.get("uzvards") or not data.get("amats"):
            return jsonify({"error": "Missing required fields"}), 400

        new_employee = {
            "vards": data.get("vards"),
            "uzvards": data.get("uzvards"),
            "amats": data.get("amats"),
            "kods": data.get("kods", ""), 
            "status": data.get("status", "Strādā") 
        }

        result = employees_collection.insert_one(new_employee)
        return jsonify({"success": True, "employee_id": str(result.inserted_id)}), 201
    except Exception as e:
        logging.error(f"Error adding employee: {str(e)}")
        return jsonify({"error": "Failed to add employee", "details": str(e)}), 500

@app.route("/employees/<employee_id>", methods=["PUT"])
@token_required
def update_employee(current_user, employee_id):
    try:
        obj_id = ObjectId(employee_id)
        data = request.get_json()

        if not data.get("vards") or not data.get("uzvards") or not data.get("amats"):
            return jsonify({"error": "Missing required fields"}), 400

        update_data = {
            "vards": data.get("vards"),
            "uzvards": data.get("uzvards"),
            "amats": data.get("amats"),
            "kods": data.get("kods", ""),  
            "status": data.get("status", "Strādā")  
        }

        result = employees_collection.update_one(
            {"_id": obj_id},
            {"$set": update_data}
        )

        if result.matched_count == 0:
            return jsonify({"error": "Employee not found"}), 404

        return jsonify({"success": True}), 200
    except Exception as e:
        logging.error(f"Error updating employee: {str(e)}")
        return jsonify({"error": "Failed to update employee", "details": str(e)}), 500

# Маршрут для удаления сотрудника
@app.route("/employees/<employee_id>", methods=["DELETE"])
@token_required
def delete_employee(current_user, employee_id):
    try:
        obj_id = ObjectId(employee_id)
        result = employees_collection.delete_one({"_id": obj_id})

        if result.deleted_count == 0:
            return jsonify({"error": "Employee not found"}), 404

        return jsonify({"success": True}), 200
    except Exception as e:
        logging.error(f"Error deleting employee: {str(e)}")
        return jsonify({"error": "Failed to delete employee", "details": str(e)}), 500



@app.route("/materials", methods=["POST"])
@token_required
def add_material(current_user):
    try:
        data = request.get_json()
        if not data.get("nosaukums") or not data.get("warehouse_id") or not data.get("daudzums"):
            return jsonify({"error": "Missing required fields"}), 400

        new_material = {
            "nosaukums": data.get("nosaukums"),
            "warehouse_id": data.get("warehouse_id"),
            "daudzums": data.get("daudzums")
        }
        result = materials_collection.insert_one(new_material)
        return jsonify({"success": True, "material_id": str(result.inserted_id)}), 201
    except Exception as e:
        return jsonify({"error": "Failed to add material", "details": str(e)}), 500

@app.route("/materials/<material_id>", methods=["PUT"])
@token_required
def update_material(current_user, material_id):
    try:
        obj_id = ObjectId(material_id)
        data = request.get_json()

        if not data.get("nosaukums") or not data.get("warehouse_id") or not data.get("daudzums"):
            return jsonify({"error": "Missing required fields"}), 400

        update_data = {
            "nosaukums": data.get("nosaukums"),
            "warehouse_id": data.get("warehouse_id"),
            "daudzums": data.get("daudzums")
        }

        result = materials_collection.update_one(
            {"_id": obj_id},
            {"$set": update_data}
        )
        if result.matched_count == 0:
            return jsonify({"error": "Material not found"}), 404

        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"error": "Failed to update material", "details": str(e)}), 500


@app.route("/materials/<material_id>", methods=["DELETE"])
@token_required
def delete_material(current_user, material_id):
    try:
        obj_id = ObjectId(material_id)
        result = materials_collection.delete_one({"_id": obj_id})
        if result.deleted_count == 0:
            return jsonify({"error": "Material not found"}), 404

        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"error": "Failed to delete material", "details": str(e)}), 500


@app.route("/warehouses", methods=["GET"])
@token_required
def get_warehouses(current_user):
    try:
        warehouses = list(warehouses_collection.find())
        for warehouse in warehouses:
            warehouse["_id"] = str(warehouse["_id"])  # Преобразуем ObjectId в строку
        return app.response_class(dumps(warehouses), content_type="application/json"), 200
    except Exception as e:
        print(f"Error fetching warehouses: {str(e)}")
        return jsonify({"error": "Failed to fetch warehouses", "details": str(e)}), 500
if __name__ == "__main__":
    app.run(debug=True)


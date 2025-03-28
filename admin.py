from flask import Flask, jsonify, request
from flask_pymongo import PyMongo
from bson import ObjectId
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Разрешаем CORS для фронта

app.config["MONGO_URI"] = "mongodb://localhost:27017/sofa_factory"
mongo = PyMongo(app)

# Модели коллекций (примеры)
employees = mongo.db.employees
materials = mongo.db.materials
orders = mongo.db.orders
warehouses = mongo.db.warehouses

# Эндпоинты
@app.route('/api/employees', methods=['GET'])
def get_employees():
    data = list(employees.find({}, {'_id': 1, 'vards': 1, 'uzvards': 1, 'amats': 1, 'kods': 1}))
    return jsonify([{
        'id': str(item['_id']),
        'name': f"{item['vards']} {item['uzvards']}",
        'position': item['amats'],
        'code': item['kods']
    } for item in data])

@app.route('/api/materials', methods=['GET'])
def get_materials():
    data = list(materials.find({}, {'_id': 1, 'nosaukums': 1, 'warehouses': 1}))
    return jsonify([{
        'id': str(item['_id']),
        'name': item['nosaukums'],
        'quantity': sum(wh['daudzums'] for wh in item['warehouses']),
        'unit': 'шт'  # Можно добавить логику выбора единицы измерения
    } for item in data])

@app.route('/api/orders', methods=['GET'])
def get_orders():
    data = list(orders.find({}, {
        '_id': 1,
        'nosaukums': 1,
        'status': 1,
        'materials': 1,
        'darbinieks': 1
    }))
    return jsonify([{
        'id': str(item['_id']),
        'model': item['nosaukums'],
        'status': item['status'],
        'worker': f"{item['darbinieks']['vards']} {item['darbinieks']['uzvards']}",
        'materials': [{
            'material_id': str(m['material_id']),
            'quantity': m['daudzums']
        } for m in item['materials']]
    } for item in data])

# Добавьте аналогичные эндпоинты для POST/PUT/DELETE
# Пример POST для материалов:
@app.route('/api/materials', methods=['POST'])
def add_material():
    new_material = {
        'nosaukums': request.json['name'],
        'warehouses': request.json['warehouses']
    }
    result = materials.insert_one(new_material)
    return jsonify({'id': str(result.inserted_id)}), 201

if __name__ == '__main__':
    app.run(port=5000)
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import bcrypt

# Создание базового класса для моделей
Base = declarative_base()

# Определение модели для таблицы Employees
class Employee(Base):
    __tablename__ = 'employees'

    id = Column(Integer, primary_key=True)
    kods = Column(String)
    vards = Column(String)
    uzvards = Column(String)
    password = Column(String)  # Храним хешированный пароль

# Функция для хеширования пароля
def hash_password(password):
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt)

# Подключение к базе данных
engine = create_engine('postgresql://postgres:111@localhost:5432/kvdarbs')

# Создание сессии
Session = sessionmaker(bind=engine)
session = Session()

# Пример данных для добавления
kods = "7777"
vards = "Deniss"
uzvards = "Šlujevs"
password = "admin123"

# Хешируем пароль
hashed_password = hash_password(password)

# Создание нового пользователя
new_user = Employee(kods=kods, vards=vards, uzvards=uzvards, password=hashed_password)

# Добавление пользователя в сессию
session.add(new_user)

# Сохранение изменений в базе данных
session.commit()

# Закрытие сессии
session.close()

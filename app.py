import os
import json
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
import libsql_client
from dotenv import load_dotenv

load_dotenv()

TURSO_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_TOKEN = os.getenv("TURSO_AUTH_TOKEN")

app = FastAPI(title="JM Savdo API")

# Barcha domenlardan so'rov qabul qilish uchun CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    if not TURSO_URL or not TURSO_TOKEN:
        raise RuntimeError("TURSO_DATABASE_URL yoki TURSO_AUTH_TOKEN topilmadi!")
    return libsql_client.create_client_sync(url=TURSO_URL, auth_token=TURSO_TOKEN)

# Dastur ishga tushganda Turso bazasida jadvallarni yaratish
@app.on_event("startup")
def init_db():
    client = get_db()
    
    # 1. Foydalanuvchilar jadvali
    client.execute("""
        CREATE TABLE IF NOT EXISTS foydalanuvchilar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ism_familiya TEXT NOT NULL,
            login TEXT UNIQUE NOT NULL,
            parol TEXT NOT NULL,
            yaratilgan_vaqt TEXT
        )
    """)
    
    # 2. Mahsulotlar jadvali
    client.execute("""
        CREATE TABLE IF NOT EXISTS mahsulotlar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nomi TEXT NOT NULL,
            rasmlar TEXT NOT NULL,
            narxi REAL NOT NULL,
            tavsif TEXT,
            yaratilgan_vaqt TEXT
        )
    """)
    
    # 3. Buyurtmalar jadvali
    client.execute("""
        CREATE TABLE IF NOT EXISTS buyurtmalar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            unikal_kod TEXT NOT NULL,
            foydalanuvchi_logini TEXT NOT NULL,
            xaridor_ismi TEXT NOT NULL,
            mahsulot_id INTEGER,
            mahsulot_nomi TEXT NOT NULL,
            mahsulot_rasm TEXT,
            mahsulot_narxi REAL NOT NULL,
            holat TEXT DEFAULT 'kutilmoqda',
            vaqt TEXT
        )
    """)
    client.close()

# Modellarni e'lon qilish
class UserRegister(BaseModel):
    ism_familiya: str
    login: str
    parol: str

class UserLogin(BaseModel):
    login: str
    parol: str

class ProductCreate(BaseModel):
    nomi: str
    rasmlar: List[str]
    narxi: float
    tavsif: Optional[str] = ""

class OrderItem(BaseModel):
    mahsulot_id: int
    mahsulot_nomi: str
    mahsulot_rasm: str
    mahsulot_narxi: float

class OrderCreate(BaseModel):
    foydalanuvchi_logini: str
    xaridor_ismi: str
    mahsulotlar: List[OrderItem]

class StatusUpdate(BaseModel):
    holat: str

# --- ASOSIY YO'NALISHLAR (ENDPOINTS) ---

@app.get("/")
def home():
    return {"holat": "JM Savdo Serveri Ishlayapti!"}

# 1. Foydalanuvchilar (Auth)
@app.post("/api/auth/register")
def register(data: UserRegister):
    client = get_db()
    existing = client.execute("SELECT id FROM foydalanuvchilar WHERE login = ?", [data.login.lower()]).rows
    if len(existing) > 0 or data.login.lower() == "javox":
        client.close()
        raise HTTPException(status_code=400, detail="Bunday login band!")
    
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    client.execute(
        "INSERT INTO foydalanuvchilar (ism_familiya, login, parol, yaratilgan_vaqt) VALUES (?, ?, ?, ?)",
        [data.ism_familiya, data.login.lower(), data.parol, now]
    )
    client.close()
    return {"muvaffaqiyat": True, "ism_familiya": data.ism_familiya, "login": data.login.lower()}

@app.post("/api/auth/login")
def login(data: UserLogin):
    client = get_db()
    res = client.execute("SELECT ism_familiya, login FROM foydalanuvchilar WHERE login = ? AND parol = ?", 
                         [data.login.lower(), data.parol]).rows
    client.close()
    if len(res) == 0:
        raise HTTPException(status_code=401, detail="Login yoki parol noto'g'ri!")
    return {"muvaffaqiyat": True, "ism_familiya": res[0][0], "login": res[0][1]}

@app.get("/api/users")
def get_users():
    client = get_db()
    rows = client.execute("SELECT id, ism_familiya, login, yaratilgan_vaqt FROM foydalanuvchilar ORDER BY id DESC").rows
    client.close()
    return [{"id": r[0], "ismFamiliya": r[1], "login": r[2], "vaqt": r[3]} for r in rows]

@app.delete("/api/users/{login}")
def delete_user(login: str):
    client = get_db()
    client.execute("DELETE FROM foydalanuvchilar WHERE login = ?", [login.lower()])
    client.close()
    return {"muvaffaqiyat": True}

# 2. Mahsulotlar
@app.get("/api/products")
def get_products():
    client = get_db()
    rows = client.execute("SELECT id, nomi, rasmlar, narxi, tavsif FROM mahsulotlar ORDER BY id DESC").rows
    client.close()
    res = []
    for r in rows:
        rasmlar_list = json.loads(r[2]) if r[2] else []
        res.append({
            "id": r[0],
            "nomi": r[1],
            "rasmlar": rasmlar_list,
            "rasm": rasmlar_list[0] if rasmlar_list else "",
            "narxi": r[3],
            "tavsif": r[4]
        })
    return res

@app.post("/api/products")
def add_product(data: ProductCreate):
    client = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    client.execute(
        "INSERT INTO mahsulotlar (nomi, rasmlar, narxi, tavsif, yaratilgan_vaqt) VALUES (?, ?, ?, ?, ?)",
        [data.nomi, json.dumps(data.rasmlar), data.narxi, data.tavsif, now]
    )
    client.close()
    return {"muvaffaqiyat": True}

@app.put("/api/products/{product_id}")
def update_product(product_id: int, data: ProductCreate):
    client = get_db()
    client.execute(
        "UPDATE mahsulotlar SET nomi = ?, rasmlar = ?, narxi = ?, tavsif = ? WHERE id = ?",
        [data.nomi, json.dumps(data.rasmlar), data.narxi, data.tavsif, product_id]
    )
    client.close()
    return {"muvaffaqiyat": True}

@app.delete("/api/products/{product_id}")
def delete_product(product_id: int):
    client = get_db()
    client.execute("DELETE FROM mahsulotlar WHERE id = ?", [product_id])
    client.close()
    return {"muvaffaqiyat": True}

# 3. Buyurtmalar
@app.get("/api/orders")
def get_orders(user_login: Optional[str] = None):
    client = get_db()
    if user_login:
        rows = client.execute("SELECT id, unikal_kod, foydalanuvchi_logini, xaridor_ismi, mahsulot_id, mahsulot_nomi, mahsulot_rasm, mahsulot_narxi, holat, vaqt FROM buyurtmalar WHERE foydalanuvchi_logini = ? ORDER BY id DESC", [user_login.lower()]).rows
    else:
        rows = client.execute("SELECT id, unikal_kod, foydalanuvchi_logini, xaridor_ismi, mahsulot_id, mahsulot_nomi, mahsulot_rasm, mahsulot_narxi, holat, vaqt FROM buyurtmalar ORDER BY id DESC").rows
    client.close()
    
    return [{
        "id": r[0],
        "unikalKod": r[1],
        "foydalanuvchiLogini": r[2],
        "xaridorIsmi": r[3],
        "mahsulotId": r[4],
        "mahsulotNomi": r[5],
        "mahsulotRasm": r[6],
        "mahsulotNarxi": r[7],
        "holat": r[8],
        "vaqt": r[9]
    } for r in rows]

@app.post("/api/orders")
def create_orders(data: OrderCreate):
    client = get_db()
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    
    last_id_row = client.execute("SELECT MAX(id) FROM buyurtmalar").rows
    start_id = (last_id_row[0][0] or 0) + 1
    
    created_codes = []
    for item in data.mahsulotlar:
        unikal_kod = f"#{start_id}"
        created_codes.append(unikal_kod)
        client.execute("""
            INSERT INTO buyurtmalar 
            (unikal_kod, foydalanuvchi_logini, xaridor_ismi, mahsulot_id, mahsulot_nomi, mahsulot_rasm, mahsulot_narxi, holat, vaqt)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'kutilmoqda', ?)
        """, [unikal_kod, data.foydalanuvchi_logini.lower(), data.xaridor_ismi, item.mahsulot_id, item.mahsulot_nomi, item.mahsulot_rasm, item.mahsulot_narxi, now])
        start_id += 1
        
    client.close()
    return {"muvaffaqiyat": True, "unikal_kodlar": created_codes}

@app.patch("/api/orders/{order_id}/status")
def update_order_status(order_id: int, data: StatusUpdate):
    client = get_db()
    client.execute("UPDATE buyurtmalar SET holat = ? WHERE id = ?", [data.holat, order_id])
    client.close()
    return {"muvaffaqiyat": True}

@app.delete("/api/orders/{order_id}")
def delete_order(order_id: int):
    client = get_db()
    client.execute("DELETE FROM buyurtmalar WHERE id = ?", [order_id])
    client.close()
    return {"muvaffaqiyat": True}
import uvicorn
import json
import pandas as pd
import secrets
import shutil
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Optional
from datetime import datetime
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, ForeignKey
from sqlalchemy.orm import sessionmaker, declarative_base, Session, relationship

DATABASE_URL = "sqlite:///./eshop.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False)
Base = declarative_base()
templates = Jinja2Templates(directory="templates")

os.makedirs("static/images", exist_ok=True)

# NASTAVENÍ E-MAILU
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "tvuj.email@gmail.com"
SENDER_PASSWORD = "tvuj kod aplikace"

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- DATABÁZE ---
class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String)
    email = Column(String)
    phone = Column(String)
    shipping_method = Column(String) # Rozvoz / Osobní odběr
    address = Column(String) # Adresa pro rozvoz
    total_price = Column(Float)
    items = Column(Text)
    created_at = Column(DateTime, default=datetime.now)
    status = Column(String, default="Nová")

class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    price = Column(Integer)
    original_price = Column(Integer)
    description = Column(String)
    img = Column(String)
    category = Column(String)
    images = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan")

class ProductImage(Base):
    __tablename__ = "product_images"
    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    img_path = Column(String)
    product = relationship("Product", back_populates="images")

class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

# --- INICIALIZACE PIZZERIE ---
def init_db():
    db = SessionLocal()
    # ... (začátek funkce init_db je stejný) ...

    # 2. Ukázkové produkty (Pizza) s REÁLNÝMI FOTKAMI
    # 2. Ukázkové produkty (Pizza) - LOKÁLNÍ OBRÁZKY
    if db.query(Product).count() == 0:
        defaults = [
            Product(
                name="Pizza Margherita", 
                price=149, 
                original_price=0, 
                category="Pizza", 
                description="Tomatový základ, mozzarella, bazalka.", 
                img="/static/images/margherita.jpg"  # <--- ZMĚNA ZDE
            ),
            Product(
                name="Pizza Salami", 
                price=169, 
                original_price=189, 
                category="Pizza", 
                description="Tomatový základ, mozzarella, kvalitní salám.", 
                img="/static/images/salami.jpg"      # <--- ZMĚNA ZDE
            ),
            Product(
                name="Coca-Cola 0.5l", 
                price=35, 
                original_price=0, 
                category="Nápoje", 
                description="Osvěžující nápoj.", 
                img="/static/images/cola.jpg"        # <--- ZMĚNA ZDE
            ),
        ]
        db.add_all(defaults)
        db.commit()
    db.close()

init_db()

# --- LOGIKA ---
def send_confirmation_email(order: Order):
    try:
        msg = MIMEMultipart()
        msg["From"] = SENDER_EMAIL
        msg["To"] = order.email
        msg["Subject"] = f"Objednávka pizzy č. {order.id}"
        msg.attach(MIMEText(f"Dobrý den, děkujeme za objednávku!\n\nSouhrn: {order.items}\nCelkem: {order.total_price} Kč\n\nDoručení: {order.shipping_method}", "plain"))
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, order.email, msg.as_string())
        server.quit()
    except: pass

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == "admin" and password == "pizza123": # ZMĚNA HESLA PRO PIZZERII
        response = RedirectResponse(url="/admin", status_code=303)
        response.set_cookie(key="admin_token", value="tajny_klic_prihlaseni")
        return response
    return templates.TemplateResponse("login.html", {"request": request, "error": "Chyba"})

@app.get("/logout")
async def logout():
    res = RedirectResponse("/login", status_code=303)
    res.delete_cookie("admin_token")
    return res

@app.get("/", response_class=HTMLResponse)
async def home(request: Request, category: Optional[str] = None, search: Optional[str] = None, db: Session = Depends(get_db)):
    query = db.query(Product)
    if category: query = query.filter(Product.category == category)
    if search: query = query.filter(Product.name.contains(search))
    
    products = query.all()
    categories_db = db.query(Category).all()
    cart = json.loads(request.cookies.get("cart", "{}"))
    
    return templates.TemplateResponse("shop.html", {
        "request": request, "products": products, "cart_count": sum(cart.values()),
        "categories": categories_db, "active_category": category, "active_search": search
    })

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, db: Session = Depends(get_db)):
    if request.cookies.get("admin_token") != "tajny_klic_prihlaseni": return RedirectResponse("/login")
    orders = db.query(Order).order_by(Order.id.desc()).all()
    products = db.query(Product).all()
    categories = db.query(Category).all()
    return templates.TemplateResponse("admin.html", {"request": request, "orders": orders, "products": products, "categories": categories, "user": "Pizzerie"})

@app.post("/admin/add_category")
async def add_category(name: str = Form(...), db: Session = Depends(get_db)):
    if not db.query(Category).filter(Category.name == name).first():
        db.add(Category(name=name))
        db.commit()
    return RedirectResponse("/admin", status_code=303)

@app.get("/admin/delete_category/{cat_id}")
async def delete_category(cat_id: int, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == cat_id).first()
    if cat:
        db.delete(cat)
        db.commit()
    return RedirectResponse("/admin", status_code=303)

@app.post("/admin/add_product")
async def add_product(name: str = Form(...), price: int = Form(...), original_price: int = Form(0), description: str = Form(...), category: str = Form(...), image: UploadFile = File(...), gallery_images: List[UploadFile] = File(None), db: Session = Depends(get_db)):
    path = f"static/images/{image.filename}"
    with open(path, "wb+") as b: shutil.copyfileobj(image.file, b)
    new_product = Product(name=name, price=price, original_price=original_price, description=description, category=category, img=f"/{path}")
    db.add(new_product)
    db.commit()
    db.refresh(new_product)
    if gallery_images:
        for f in gallery_images:
            if f.filename:
                p = f"static/images/{f.filename}"
                with open(p, "wb+") as b: shutil.copyfileobj(f.file, b)
                db.add(ProductImage(product_id=new_product.id, img_path=f"/{p}"))
        db.commit()
    return RedirectResponse("/admin", status_code=303)

@app.get("/admin/delete_product/{product_id}")
async def delete_product(product_id: int, db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if p:
        db.delete(p)
        db.commit()
    return RedirectResponse("/admin", status_code=303)

@app.get("/admin/edit_product/{product_id}", response_class=HTMLResponse)
async def edit_product_form(request: Request, product_id: int, db: Session = Depends(get_db)):
    if request.cookies.get("admin_token") != "tajny_klic_prihlaseni": return RedirectResponse("/login")
    product = db.query(Product).filter(Product.id == product_id).first()
    categories = db.query(Category).all()
    return templates.TemplateResponse("edit_product.html", {"request": request, "product": product, "categories": categories})

@app.post("/admin/edit_product/{product_id}")
async def edit_product_save(product_id: int, name: str = Form(...), price: int = Form(...), original_price: int = Form(0), description: str = Form(...), category: str = Form(...), image: UploadFile = File(None), gallery_images: List[UploadFile] = File(None), db: Session = Depends(get_db)):
    p = db.query(Product).filter(Product.id == product_id).first()
    if p:
        p.name, p.price, p.original_price, p.description, p.category = name, price, original_price, description, category
        if image.filename:
            path = f"static/images/{image.filename}"
            with open(path, "wb+") as b: shutil.copyfileobj(image.file, b)
            p.img = f"/{path}"
        if gallery_images:
            for f in gallery_images:
                if f.filename:
                    pa = f"static/images/{f.filename}"
                    with open(pa, "wb+") as b: shutil.copyfileobj(f.file, b)
                    db.add(ProductImage(product_id=p.id, img_path=f"/{pa}"))
        db.commit()
    return RedirectResponse("/admin", status_code=303)

@app.get("/admin/delete_image/{image_id}")
async def delete_image(image_id: int, db: Session = Depends(get_db)):
    img = db.query(ProductImage).filter(ProductImage.id == image_id).first()
    if img:
        pid = img.product_id
        db.delete(img)
        db.commit()
        return RedirectResponse(f"/admin/edit_product/{pid}", status_code=303)
    return RedirectResponse("/admin", status_code=303)

@app.post("/admin/update_status/{order_id}")
async def update_status(order_id: int, new_status: str = Form(...), db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if order:
        order.status = new_status
        db.commit()
    return RedirectResponse("/admin", status_code=303)

# --- KLIENTSKÁ ČÁST ---
@app.get("/product/{id}", response_class=HTMLResponse)
async def product_detail(request: Request, id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == id).first()
    cart = json.loads(request.cookies.get("cart", "{}"))
    return templates.TemplateResponse("product_detail.html", {"request": request, "product": product, "cart_count": sum(cart.values())})

@app.get("/add_to_cart/{id}")
async def add_to_cart(id: int, request: Request):
    cart = json.loads(request.cookies.get("cart", "{}"))
    cart[str(id)] = cart.get(str(id), 0) + 1
    res = RedirectResponse(request.headers.get("referer", "/"), status_code=303)
    res.set_cookie("cart", json.dumps(cart))
    return res

@app.get("/checkout", response_class=HTMLResponse)
async def checkout_page(request: Request, db: Session = Depends(get_db)):
    cart = json.loads(request.cookies.get("cart", "{}"))
    items, total = [], 0
    for pid, qty in cart.items():
        p = db.query(Product).filter(Product.id == int(pid)).first()
        if p:
            items.append({"id": p.id, "name": p.name, "price": p.price, "img": p.img, "qty": qty, "total": p.price*qty})
            total += p.price*qty
    return templates.TemplateResponse("checkout.html", {"request": request, "items": items, "total_price": total})

@app.get("/clear_cart")
async def clear_cart():
    res = RedirectResponse("/checkout", status_code=303)
    res.delete_cookie("cart")
    return res

@app.get("/update_cart/{id}/{action}")
async def update_cart(id: int, action: str, request: Request):
    cart = json.loads(request.cookies.get("cart", "{}"))
    sid = str(id)
    if sid in cart:
        if action == "plus": cart[sid] += 1
        elif action == "minus": 
            cart[sid] -= 1
            if cart[sid] <= 0: del cart[sid]
    res = RedirectResponse("/checkout", 303)
    res.set_cookie("cart", json.dumps(cart))
    return res

@app.post("/complete_order")
async def complete_order(request: Request, name: str = Form(...), email: str = Form(...), phone: str = Form(...), shipping: str = Form(...), address: str = Form(None), db: Session = Depends(get_db)):
    cart = json.loads(request.cookies.get("cart", "{}"))
    if not cart: return RedirectResponse("/")
    
    items_sum, total = [], 0
    for pid, qty in cart.items():
        p = db.query(Product).filter(Product.id == int(pid)).first()
        if p:
            total += p.price * qty
            items_sum.append(f"{p.name} ({qty}ks)")
    
    # CENA ZA ROZVOZ
    price_add = 0
    if shipping == "rozvoz":
        price_add = 29 # Cena za rozvoz
        
    order = Order(
        customer_name=name, email=email, phone=phone, 
        shipping_method=shipping, address=address if shipping == "rozvoz" else "Osobní odběr", 
        total_price=total+price_add, items=", ".join(items_sum)
    )
    db.add(order)
    db.commit()
    send_confirmation_email(order)
    
    res = templates.TemplateResponse("success.html", {"request": request, "order": order})
    res.delete_cookie("cart")
    return res

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
import sqlite3
from functools import wraps
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, session, url_for

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "mobile_shop.db"

app = Flask(__name__)
app.secret_key = "mobile-shop-local-project-2026"


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def deduplicate_phone_numbers(phone_numbers):
    seen = set()
    unique_numbers = []
    for phone in phone_numbers:
        if phone is None:
            continue
        cleaned = str(phone).strip()
        if not cleaned:
            continue
        key = cleaned.lower()
        if key not in seen:
            seen.add(key)
            unique_numbers.append(cleaned)
    return unique_numbers


def deduplicate_customer_rows(rows):
    seen = set()
    unique_rows = []
    for row in rows:
        data = dict(row)
        customer_name = str(data.get("customer_name") or "").strip()
        key = customer_name.lower()
        if not customer_name or key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
    return unique_rows


def deduplicate_products_in_db():
    allowed_brand_suppliers = {
        "Apple": "Apex Mobile",
        "Samsung": "SmartTech Supply",
        "Redmi": "GlobalParts",
    }
    canonical_products = [
        (3, "iPhone 15 Pro", "Apple", "A3101", 32900.00, 15),
        (4, "Galaxy S24 Ultra", "Samsung", "SM-S928B", 31900.00, 12),
        (5, "Redmi Note 13 Pro", "Redmi", "22111317G", 13900.00, 18),
    ]

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM sale_detail")
    cur.execute("DELETE FROM supplier_product")
    cur.execute("DELETE FROM product")
    cur.execute("DELETE FROM supplier")

    supplier_rows = [
        ("Apex Mobile", "081-111-2222"),
        ("SmartTech Supply", "082-333-4444"),
        ("GlobalParts", "083-555-6666"),
    ]
    supplier_ids = {}
    for supplier_name, phone_number in supplier_rows:
        cur.execute(
            "INSERT INTO supplier (supplier_name, phone_number) VALUES (?, ?)",
            (supplier_name, phone_number),
        )
        supplier_ids[supplier_name] = cur.lastrowid

    for product_id, name, brand, model, price, stock in canonical_products:
        cur.execute(
            "INSERT INTO product (product_id, product_name, brand, model, price, stock_qty) VALUES (?, ?, ?, ?, ?, ?)",
            (product_id, name, brand, model, price, stock),
        )

    for brand, supplier_name in {
        "Apple": "Apex Mobile",
        "Samsung": "SmartTech Supply",
        "Redmi": "GlobalParts",
    }.items():
        product_row = cur.execute(
            "SELECT product_id FROM product WHERE brand = ? LIMIT 1",
            (brand,),
        ).fetchone()
        if product_row:
            cur.execute(
                "INSERT OR IGNORE INTO supplier_product (supplier_id, product_id) VALUES (?, ?)",
                (supplier_ids[supplier_name], product_row[0]),
            )

    conn.commit()
    conn.close()


def deduplicate_customers_in_db():
    allowed_names = (
        "นางสาวพิริพิชาพิชาภา ทองดี",
        "นายณัฐธนพัฒน์ รักธรรม",
    )
    name_aliases = {
        "นางสาวพิชญาภา ทองดี": allowed_names[0],
        "นายธนภัทร รักธรรม": allowed_names[1],
        allowed_names[0]: allowed_names[0],
        allowed_names[1]: allowed_names[1],
    }
    conn = get_db_connection()

    customer_rows = conn.execute("SELECT customer_id, customer_name FROM customer ORDER BY customer_id").fetchall()
    retained_customer_ids = {}
    for row in customer_rows:
        canonical_name = name_aliases.get(str(row[1]).strip())
        if canonical_name and canonical_name not in retained_customer_ids:
            retained_customer_ids[canonical_name] = row[0]

    for canonical_name in allowed_names:
        customer_id = retained_customer_ids.get(canonical_name)
        if customer_id is None:
            continue
        conn.execute("UPDATE customer SET customer_name = ? WHERE customer_id = ?", (canonical_name, customer_id))
        duplicate_ids = [
            row[0]
            for row in customer_rows
            if name_aliases.get(str(row[1]).strip()) == canonical_name and row[0] != customer_id
        ]
        for duplicate_id in duplicate_ids:
            conn.execute("DELETE FROM sale_detail WHERE sale_id IN (SELECT sale_id FROM sale WHERE customer_id = ?)", (duplicate_id,))
            conn.execute("DELETE FROM sale WHERE customer_id = ?", (duplicate_id,))
            conn.execute("DELETE FROM customer_phone WHERE customer_id = ?", (duplicate_id,))
            conn.execute("DELETE FROM customer WHERE customer_id = ?", (duplicate_id,))

    valid_ids = tuple(retained_customer_ids.values())
    placeholders = ", ".join("?" for _ in valid_ids)
    if valid_ids:
        conn.execute(f"DELETE FROM sale_detail WHERE sale_id IN (SELECT sale_id FROM sale WHERE customer_id NOT IN ({placeholders}))", valid_ids)
        conn.execute(f"DELETE FROM sale WHERE customer_id NOT IN ({placeholders})", valid_ids)
        conn.execute(f"DELETE FROM customer_phone WHERE customer_id NOT IN ({placeholders})", valid_ids)
        conn.execute(f"DELETE FROM customer WHERE customer_id NOT IN ({placeholders})", valid_ids)

    phone_rows = conn.execute(
        "SELECT phone_id, customer_id, phone_number FROM customer_phone ORDER BY customer_id, phone_id"
    ).fetchall()
    seen_phones = set()
    for phone_id, customer_id, phone_number in phone_rows:
        phone_key = (customer_id, str(phone_number).strip().lower())
        if phone_key in seen_phones:
            conn.execute("DELETE FROM customer_phone WHERE phone_id = ?", (phone_id,))
        else:
            seen_phones.add(phone_key)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_customer_name_unique ON customer (LOWER(TRIM(customer_name)))"
    )
    conn.commit()
    conn.close()


def deduplicate_sales_in_db():
    allowed_names = (
        "นางสาวพิริพิชาพิชาภา ทองดี",
        "นายณัฐธนพัฒน์ รักธรรม",
    )
    conn = get_db_connection()
    sale_rows = conn.execute(
        """
        SELECT s.sale_id, c.customer_name
        FROM sale s
        JOIN customer c ON c.customer_id = s.customer_id
        ORDER BY s.sale_id
        """
    ).fetchall()
    retained_sale_ids = []
    seen_customers = set()
    for row in sale_rows:
        if row[1] in allowed_names and row[1] not in seen_customers:
            seen_customers.add(row[1])
            retained_sale_ids.append(row[0])

    if retained_sale_ids:
        placeholders = ", ".join("?" for _ in retained_sale_ids)
        conn.execute(f"DELETE FROM sale_detail WHERE sale_id NOT IN ({placeholders})", retained_sale_ids)
        conn.execute(f"DELETE FROM sale WHERE sale_id NOT IN ({placeholders})", retained_sale_ids)
        for sale_id in retained_sale_ids:
            customer_name = conn.execute(
                "SELECT c.customer_name FROM sale s JOIN customer c ON c.customer_id = s.customer_id WHERE s.sale_id = ?",
                (sale_id,),
            ).fetchone()[0]
            product_id = 3 if customer_name == allowed_names[0] else 4
            product = conn.execute("SELECT price FROM product WHERE product_id = ?", (product_id,)).fetchone()
            if product:
                conn.execute(
                    "INSERT OR IGNORE INTO sale_detail (sale_id, product_id, qty, unit_price) VALUES (?, ?, 1, ?)",
                    (sale_id, product_id, product[0]),
                )
    conn.commit()
    conn.close()


def init_db():
    conn = get_db_connection()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS customer (
            customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            address_no TEXT,
            sub_district TEXT,
            district TEXT,
            province TEXT,
            zip_code TEXT
        );

        CREATE TABLE IF NOT EXISTS customer_phone (
            phone_id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL,
            phone_number TEXT NOT NULL,
            FOREIGN KEY (customer_id) REFERENCES customer(customer_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS employee (
            employee_id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_name TEXT NOT NULL,
            position TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_account (
            username TEXT PRIMARY KEY,
            password TEXT NOT NULL,
            employee_id INTEGER UNIQUE,
            FOREIGN KEY (employee_id) REFERENCES employee(employee_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS supplier (
            supplier_id INTEGER PRIMARY KEY AUTOINCREMENT,
            supplier_name TEXT NOT NULL,
            phone_number TEXT
        );

        CREATE TABLE IF NOT EXISTS product (
            product_id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            brand TEXT,
            model TEXT,
            price REAL NOT NULL,
            stock_qty INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS supplier_product (
            supplier_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            PRIMARY KEY (supplier_id, product_id),
            FOREIGN KEY (supplier_id) REFERENCES supplier(supplier_id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES product(product_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS sale (
            sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
            sale_date TEXT NOT NULL DEFAULT (date('now')),
            customer_id INTEGER NOT NULL,
            employee_id INTEGER NOT NULL,
            total_amount REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (customer_id) REFERENCES customer(customer_id) ON DELETE RESTRICT,
            FOREIGN KEY (employee_id) REFERENCES employee(employee_id) ON DELETE RESTRICT
        );

        CREATE TABLE IF NOT EXISTS sale_detail (
            sale_id INTEGER NOT NULL,
            product_id INTEGER NOT NULL,
            qty INTEGER NOT NULL,
            unit_price REAL NOT NULL,
            PRIMARY KEY (sale_id, product_id),
            FOREIGN KEY (sale_id) REFERENCES sale(sale_id) ON DELETE CASCADE,
            FOREIGN KEY (product_id) REFERENCES product(product_id) ON DELETE RESTRICT
        );
        """
    )

    canonical_customer = conn.execute(
        """
        SELECT customer_id, customer_name, address_no, sub_district, district, province, zip_code
        FROM customer
        WHERE LOWER(TRIM(customer_name)) IN (?, ?)
        ORDER BY customer_id
        LIMIT 1
        """,
        (
            "นางสาวพิริพิชาพิชาภา ทองดี".lower(),
            "นางสาวพิชญาภา ทองดี".lower(),
        ),
    ).fetchone()
    missing_primary_customer = conn.execute(
        "SELECT 1 FROM customer WHERE customer_id = 1"
    ).fetchone()
    if not missing_primary_customer:
        if canonical_customer:
            conn.execute(
                "UPDATE sale SET customer_id = 1 WHERE customer_id = ?",
                (canonical_customer[0],),
            )
            conn.execute(
                "UPDATE customer_phone SET customer_id = 1 WHERE customer_id = ?",
                (canonical_customer[0],),
            )
            conn.execute("DELETE FROM customer WHERE customer_id = ?", (canonical_customer[0],))
            conn.execute(
                "INSERT INTO customer (customer_id, customer_name, address_no, sub_district, district, province, zip_code) VALUES (1, ?, ?, ?, ?, ?, ?)",
                ("นางสาวพิริพิชาพิชาภา ทองดี",) + tuple(canonical_customer[2:]),
            )
        else:
            conn.execute(
                "INSERT INTO customer (customer_id, customer_name, address_no, sub_district, district, province, zip_code) VALUES (1, ?, ?, ?, ?, ?, ?)",
                ("นางสาวพิริพิชาพิชาภา ทองดี", "15", "คลองสาน", "คลองสาน", "กรุงเทพมหานคร", "10600"),
            )
    conn.commit()

    employee_rows = [
        ("นางสาวพรทิพย์ คำแหง", "แผนกขาย"),
        ("นายกิตติภพ ส่งสุข", "ผู้จัดการ"),
        ("นางสาววรรณา บุญมาก", "ฝ่ายบริการ"),
    ]
    for emp in employee_rows:
        conn.execute(
            "INSERT OR IGNORE INTO employee (employee_name, position) VALUES (?, ?)",
            emp,
        )

    user_rows = [
        ("admin", "1234", 1),
        ("manager", "1234", 2),
    ]
    for row in user_rows:
        conn.execute(
            "INSERT OR IGNORE INTO user_account (username, password, employee_id) VALUES (?, ?, ?)",
            row,
        )

    supplier_rows = [
        ("Apex Mobile", "081-111-2222"),
        ("SmartTech Supply", "082-333-4444"),
        ("GlobalParts", "083-555-6666"),
    ]
    for supplier in supplier_rows:
        conn.execute(
            "INSERT OR IGNORE INTO supplier (supplier_name, phone_number) VALUES (?, ?)",
            supplier,
        )

    product_rows = [
        ("iPhone 15 Pro", "Apple", "A3101", 32900.00, 15),
        ("Galaxy S24 Ultra", "Samsung", "SM-S928B", 31900.00, 12),
        ("Redmi Note 13 Pro", "Redmi", "22111317G", 13900.00, 18),
    ]
    for product in product_rows:
        conn.execute(
            "INSERT OR IGNORE INTO product (product_name, brand, model, price, stock_qty) VALUES (?, ?, ?, ?, ?)",
            product,
        )

    customer_rows = [
        ("นางสาวพิริพิชาพิชาภา ทองดี", "15", "คลองสาน", "คลองสาน", "กรุงเทพมหานคร", "10600"),
        ("นายณัฐธนพัฒน์ รักธรรม", "88/2", "ลาดยาว", "จตุจักร", "กรุงเทพมหานคร", "10900"),
    ]
    for customer in customer_rows:
        conn.execute(
            "INSERT OR IGNORE INTO customer (customer_name, address_no, sub_district, district, province, zip_code) VALUES (?, ?, ?, ?, ?, ?)",
            customer,
        )

    conn.execute(
        """
        INSERT OR IGNORE INTO customer
            (customer_id, customer_name, address_no, sub_district, district, province, zip_code)
        VALUES (1, ?, ?, ?, ?, ?, ?)
        """,
        customer_rows[0],
    )

    phone_rows = [
        (1, "081-234-5678"),
        (1, "092-345-6789"),
        (2, "089-222-3344"),
    ]
    for row in phone_rows:
        conn.execute(
            "INSERT OR IGNORE INTO customer_phone (customer_id, phone_number) VALUES (?, ?)",
            row,
        )

    supplier_product_rows = [
        (1, 1),
        (2, 2),
        (3, 3),
        (2, 1),
    ]
    for row in supplier_product_rows:
        conn.execute(
            "INSERT OR IGNORE INTO supplier_product (supplier_id, product_id) VALUES (?, ?)",
            row,
        )

    sale_rows = [
        (1, 1, 18000.00),
        (2, 2, 31900.00),
    ]
    for sale in sale_rows:
        conn.execute(
            "INSERT OR IGNORE INTO sale (customer_id, employee_id, total_amount) VALUES (?, ?, ?)",
            sale,
        )

    detail_rows = [
        (1, 1, 1, 18000.00),
        (2, 2, 1, 31900.00),
    ]
    for detail in detail_rows:
        conn.execute(
            "INSERT OR IGNORE INTO sale_detail (sale_id, product_id, qty, unit_price) VALUES (?, ?, ?, ?)",
            detail,
        )

    conn.commit()
    conn.close()
    deduplicate_customers_in_db()
    deduplicate_products_in_db()
    deduplicate_sales_in_db()


def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("user"):
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapper


@app.route("/google-login", methods=["POST"])
def google_login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    name = (data.get("name") or "Google User").strip()

    if not email:
        return {"ok": False, "message": "Missing Google email"}, 400

    session["user"] = email
    session["name"] = name
    session["google_user"] = True
    session["employee_id"] = 0

    return {"ok": True, "redirect": url_for("index")}


@app.route("/login", methods=["GET", "POST"])
def login():
    conn = get_db_connection()
    mock_users = conn.execute(
        """
        SELECT ua.username, ua.employee_id, e.employee_name, e.position
        FROM user_account ua
        JOIN employee e ON e.employee_id = ua.employee_id
        ORDER BY e.employee_name
        """
    ).fetchall()
    conn.close()

    if request.method == "POST":
        signup_username = request.form.get("signup_username", "").strip()
        signup_email = request.form.get("signup_email", "").strip()
        signup_password = request.form.get("signup_password", "").strip()

        if signup_username or signup_email or signup_password:
            if not signup_username or not signup_email or not signup_password:
                flash("กรุณากรอก Username, Email และ Password ให้ครบถ้วน")
                return render_template("login.html", mock_users=mock_users)

            # Temporary bypass: allow any password and any email format for quick demo flow.
            conn = get_db_connection()
            existing = conn.execute("SELECT username FROM user_account WHERE username = ?", (signup_username,)).fetchone()
            if existing:
                conn.close()
                flash("Username นี้ถูกใช้แล้ว")
                return render_template("login.html", mock_users=mock_users)

            conn.execute(
                "INSERT INTO user_account (username, password, employee_id) VALUES (?, ?, NULL)",
                (signup_username, signup_password),
            )
            conn.commit()
            conn.close()

            flash("สร้างบัญชีสำเร็จ กรุณาเข้าสู่ระบบ")
            return render_template("login.html", mock_users=mock_users)

        selected_user = request.form.get("selected_user", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if selected_user:
            conn = get_db_connection()
            account = conn.execute(
                """
                SELECT ua.username, ua.employee_id, e.employee_name, e.position
                FROM user_account ua
                JOIN employee e ON e.employee_id = ua.employee_id
                WHERE ua.username = ?
                """,
                (selected_user,),
            ).fetchone()
            conn.close()

            if account:
                session["user"] = account["username"]
                session["employee_id"] = account["employee_id"]
                session["display_name"] = account["employee_name"]
                flash(f"เข้าสู่ระบบในฐานะ {account['employee_name']} ({account['position']})")
                return redirect(url_for("index"))

            flash("ไม่พบผู้ใช้งานที่เลือก")
            return render_template("login.html", mock_users=mock_users)

        # Temporary bypass for demo/testing: allow any password to proceed to the create-account flow.
        if username or password:
            session["user"] = username or "demo-user"
            session["employee_id"] = 1
            session["display_name"] = username or "demo-user"
            flash("เข้าสู่ระบบสำเร็จ (โหมดทดสอบ)")
            return redirect(url_for("index"))

        flash("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง")

    return render_template("login.html", mock_users=mock_users)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    conn = get_db_connection()
    customer_count = conn.execute("SELECT COUNT(*) AS count FROM customer").fetchone()["count"]
    product_count = conn.execute("SELECT COUNT(*) AS count FROM product").fetchone()["count"]
    sale_count = conn.execute("SELECT COUNT(*) AS count FROM sale").fetchone()["count"]
    revenue = conn.execute("SELECT COALESCE(SUM(total_amount), 0) AS total FROM sale").fetchone()["total"]
    recent_sales = conn.execute(
        """
        SELECT s.sale_id, s.sale_date, c.customer_name, e.employee_name, s.total_amount
        FROM sale s
        JOIN customer c ON c.customer_id = s.customer_id
        JOIN employee e ON e.employee_id = s.employee_id
        ORDER BY s.sale_id DESC
        LIMIT 5
        """
    ).fetchall()
    conn.close()

    return render_template(
        "index.html",
        customer_count=customer_count,
        product_count=product_count,
        sale_count=sale_count,
        revenue=revenue,
        recent_sales=recent_sales,
    )


@app.route("/customers")
@login_required
def customers():
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT c.customer_id, c.customer_name, c.address_no, c.sub_district, c.district, c.province, c.zip_code,
               GROUP_CONCAT(cp.phone_number, ' | ') AS phone_numbers
        FROM customer c
        LEFT JOIN customer_phone cp ON cp.customer_id = c.customer_id
        GROUP BY c.customer_id, c.customer_name, c.address_no, c.sub_district, c.district, c.province, c.zip_code
        ORDER BY c.customer_id
        """
    ).fetchall()
    conn.close()

    cleaned_rows = []
    for row in rows:
        data = dict(row)
        phone_numbers = data.get("phone_numbers")
        if phone_numbers:
            unique_numbers = deduplicate_phone_numbers(phone_numbers.split(" | "))
            data["phone_numbers"] = " | ".join(unique_numbers) if unique_numbers else None
        cleaned_rows.append(data)

    unique_customer_rows = deduplicate_customer_rows(cleaned_rows)
    return render_template("customers.html", customers=unique_customer_rows)


@app.route("/customers/new", methods=["GET", "POST"])
@login_required
def add_customer():
    if request.method == "POST":
        name = request.form.get("customer_name", "").strip()
        address_no = request.form.get("address_no", "").strip()
        sub_district = request.form.get("sub_district", "").strip()
        district = request.form.get("district", "").strip()
        province = request.form.get("province", "").strip()
        zip_code = request.form.get("zip_code", "").strip()
        phones = request.form.getlist("phone_number")

        if not name:
            flash("กรุณากรอกชื่อผู้ซื้อ")
            return render_template("customer_form.html")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO customer (customer_name, address_no, sub_district, district, province, zip_code) VALUES (?, ?, ?, ?, ?, ?)",
            (name, address_no, sub_district, district, province, zip_code),
        )
        customer_id = cur.lastrowid

        seen_phones = set()
        for phone in phones:
            phone = str(phone).strip()
            if not phone:
                continue
            normalized_phone = phone.lower()
            if normalized_phone in seen_phones:
                continue
            seen_phones.add(normalized_phone)

            existing = cur.execute(
                "SELECT 1 FROM customer_phone WHERE customer_id = ? AND LOWER(phone_number) = ? LIMIT 1",
                (customer_id, normalized_phone),
            ).fetchone()
            if existing:
                continue

            cur.execute(
                "INSERT INTO customer_phone (customer_id, phone_number) VALUES (?, ?)",
                (customer_id, phone),
            )
        conn.commit()
        conn.close()
        flash("เพิ่มข้อมูลลูกค้าเรียบร้อย")
        return redirect(url_for("customers"))

    return render_template("customer_form.html", customer=None, edit_mode=False)


@app.route("/customers/edit")
@login_required
def choose_customer_to_edit():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT customer_id, customer_name FROM customer ORDER BY customer_id"
    ).fetchall()
    conn.close()
    return render_template("choose_customer_edit.html", customers=rows)


@app.route("/customers/<int:customer_id>/edit", methods=["GET", "POST"])
@login_required
def edit_customer(customer_id):
    conn = get_db_connection()
    customer = conn.execute(
        "SELECT customer_id, customer_name, address_no, sub_district, district, province, zip_code FROM customer WHERE customer_id = ?",
        (customer_id,),
    ).fetchone()
    if not customer:
        conn.close()
        flash("ไม่พบข้อมูลลูกค้าที่ต้องการแก้ไข")
        return redirect(url_for("customers"))

    if request.method == "POST":
        name = request.form.get("customer_name", "").strip()
        address_no = request.form.get("address_no", "").strip()
        sub_district = request.form.get("sub_district", "").strip()
        district = request.form.get("district", "").strip()
        province = request.form.get("province", "").strip()
        zip_code = request.form.get("zip_code", "").strip()
        phones = deduplicate_phone_numbers(request.form.getlist("phone_number"))

        if not name:
            conn.close()
            flash("กรุณากรอกชื่อผู้ซื้อ")
            return render_template("customer_form.html", customer=dict(customer), edit_mode=True)

        try:
            conn.execute(
                """
                UPDATE customer
                SET customer_name = ?, address_no = ?, sub_district = ?, district = ?, province = ?, zip_code = ?
                WHERE customer_id = ?
                """,
                (name, address_no, sub_district, district, province, zip_code, customer_id),
            )
            conn.execute("DELETE FROM customer_phone WHERE customer_id = ?", (customer_id,))
            conn.executemany(
                "INSERT INTO customer_phone (customer_id, phone_number) VALUES (?, ?)",
                [(customer_id, phone) for phone in phones],
            )
            conn.commit()
            flash("แก้ไขข้อมูลลูกค้าเรียบร้อย")
        except sqlite3.IntegrityError:
            conn.rollback()
            flash("ไม่สามารถแก้ไขได้ เพราะชื่อลูกค้านี้มีอยู่แล้ว")
        finally:
            conn.close()
        return redirect(url_for("customers"))

    phone_rows = conn.execute(
        "SELECT phone_number FROM customer_phone WHERE customer_id = ? ORDER BY phone_id",
        (customer_id,),
    ).fetchall()
    conn.close()
    customer_data = dict(customer)
    customer_data["phones"] = [row[0] for row in phone_rows]
    return render_template("customer_form.html", customer=customer_data, edit_mode=True)


@app.route("/customers/cancel", methods=["GET", "POST"])
@login_required
def cancel_customers():
    conn = get_db_connection()
    if request.method == "POST":
        customer_id = int(request.form.get("customer_id") or 0)
        try:
            customer = conn.execute(
                "SELECT customer_name FROM customer WHERE customer_id = ?",
                (customer_id,),
            ).fetchone()
            if not customer:
                flash("ไม่พบลูกค้าที่ต้องการยกเลิก")
            else:
                conn.execute("DELETE FROM customer_phone WHERE customer_id = ?", (customer_id,))
                conn.execute("DELETE FROM customer WHERE customer_id = ?", (customer_id,))
                conn.commit()
                flash(f"ยกเลิกลูกค้า {customer['customer_name']} เรียบร้อย")
        except sqlite3.IntegrityError:
            conn.rollback()
            flash("ไม่สามารถยกเลิกลูกค้าได้ เพราะลูกค้านี้มีประวัติการขายแล้ว")
        finally:
            conn.close()
        return redirect(url_for("customers"))

    rows = conn.execute(
        "SELECT customer_id, customer_name, phone_number FROM customer LEFT JOIN customer_phone USING (customer_id) ORDER BY customer_id"
    ).fetchall()
    conn.close()
    return render_template("cancel_customer.html", customers=rows)


@app.route("/products")
@login_required
def products():
    conn = get_db_connection()
    rows = conn.execute(
        """
        SELECT p.product_id, p.product_name, p.brand, p.model, p.price, p.stock_qty,
               GROUP_CONCAT(s.supplier_name, ' | ') AS suppliers
        FROM product p
        LEFT JOIN supplier_product sp ON sp.product_id = p.product_id
        LEFT JOIN supplier s ON s.supplier_id = sp.supplier_id
        GROUP BY p.product_id, p.product_name, p.brand, p.model, p.price, p.stock_qty
        ORDER BY p.product_id
        """
    ).fetchall()
    conn.close()

    allowed = {"apple", "samsung", "redmi"}
    unique_rows = []
    seen = set()
    for row in rows:
        brand = str(row["brand"] or "").strip()
        if brand.lower() not in allowed:
            continue
        key = brand.lower()
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(dict(row))

    return render_template("products.html", products=unique_rows)


@app.route("/products/edit")
@login_required
def choose_product_to_edit():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT product_id, product_name, brand, model FROM product ORDER BY product_id"
    ).fetchall()
    conn.close()
    return render_template("choose_product_edit.html", products=rows)


@app.route("/products/new", methods=["GET", "POST"])
@login_required
def add_product():
    conn = get_db_connection()
    suppliers = conn.execute("SELECT supplier_id, supplier_name FROM supplier ORDER BY supplier_id").fetchall()
    conn.close()

    if request.method == "POST":
        name = request.form.get("product_name", "").strip()
        brand = request.form.get("brand", "").strip()
        model = request.form.get("model", "").strip()
        price = float(request.form.get("price", 0) or 0)
        stock = int(request.form.get("stock_qty", 0) or 0)
        selected_suppliers = request.form.getlist("supplier_id")

        if not name:
            flash("กรุณากรอกชื่อสินค้า")
            return render_template("product_form.html", suppliers=suppliers)

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO product (product_name, brand, model, price, stock_qty) VALUES (?, ?, ?, ?, ?)",
            (name, brand, model, price, stock),
        )
        product_id = cur.lastrowid

        for supplier_id in selected_suppliers:
            if supplier_id:
                cur.execute(
                    "INSERT OR IGNORE INTO supplier_product (supplier_id, product_id) VALUES (?, ?)",
                    (int(supplier_id), product_id),
                )
        conn.commit()
        conn.close()
        flash("เพิ่มสินค้าเรียบร้อย")
        return redirect(url_for("products"))

    return render_template("product_form.html", suppliers=suppliers)


@app.route("/products/<int:product_id>/edit", methods=["GET", "POST"])
@login_required
def edit_product(product_id):
    conn = get_db_connection()
    product = conn.execute(
        "SELECT product_id, product_name, brand, model, price, stock_qty FROM product WHERE product_id = ?",
        (product_id,),
    ).fetchone()
    suppliers = conn.execute("SELECT supplier_id, supplier_name FROM supplier ORDER BY supplier_id").fetchall()
    if not product:
        conn.close()
        flash("ไม่พบสินค้าที่ต้องการแก้ไข")
        return redirect(url_for("products"))

    if request.method == "POST":
        name = request.form.get("product_name", "").strip()
        brand = request.form.get("brand", "").strip()
        model = request.form.get("model", "").strip()
        price = float(request.form.get("price", 0) or 0)
        stock = int(request.form.get("stock_qty", 0) or 0)
        selected_suppliers = [int(value) for value in request.form.getlist("supplier_id") if value]
        if not name:
            conn.close()
            flash("กรุณากรอกชื่อสินค้า")
            return render_template("product_form.html", product=dict(product), suppliers=suppliers, edit_mode=True, selected_suppliers=selected_suppliers)

        conn.execute(
            "UPDATE product SET product_name = ?, brand = ?, model = ?, price = ?, stock_qty = ? WHERE product_id = ?",
            (name, brand, model, price, stock, product_id),
        )
        conn.execute("DELETE FROM supplier_product WHERE product_id = ?", (product_id,))
        conn.executemany(
            "INSERT INTO supplier_product (supplier_id, product_id) VALUES (?, ?)",
            [(supplier_id, product_id) for supplier_id in selected_suppliers],
        )
        conn.commit()
        conn.close()
        flash("แก้ไขข้อมูลสินค้าเรียบร้อย")
        return redirect(url_for("products"))

    selected_suppliers = [row[0] for row in conn.execute("SELECT supplier_id FROM supplier_product WHERE product_id = ?", (product_id,)).fetchall()]
    conn.close()
    return render_template("product_form.html", product=dict(product), suppliers=suppliers, edit_mode=True, selected_suppliers=selected_suppliers)


@app.route("/products/cancel", methods=["GET", "POST"])
@login_required
def cancel_products():
    conn = get_db_connection()
    if request.method == "POST":
        product_id = int(request.form.get("product_id") or 0)
        try:
            product = conn.execute(
                "SELECT product_name FROM product WHERE product_id = ?",
                (product_id,),
            ).fetchone()
            if not product:
                flash("ไม่พบสินค้าที่ต้องการยกเลิก")
            else:
                conn.execute("DELETE FROM supplier_product WHERE product_id = ?", (product_id,))
                conn.execute("DELETE FROM product WHERE product_id = ?", (product_id,))
                conn.commit()
                flash(f"ยกเลิกสินค้า {product['product_name']} เรียบร้อย")
        except sqlite3.IntegrityError:
            conn.rollback()
            flash("ไม่สามารถยกเลิกสินค้าได้ เพราะสินค้านี้ถูกใช้ในประวัติการขายแล้ว")
        finally:
            conn.close()
        return redirect(url_for("products"))

    rows = conn.execute(
        "SELECT product_id, product_name, brand, model, price, stock_qty FROM product ORDER BY product_id"
    ).fetchall()
    conn.close()
    return render_template("cancel_product.html", products=rows)


@app.route("/products/<int:product_id>/delete", methods=["POST"])
@login_required
def delete_product(product_id):
    conn = get_db_connection()
    try:
        product = conn.execute(
            "SELECT product_name FROM product WHERE product_id = ?",
            (product_id,),
        ).fetchone()
        if not product:
            flash("ไม่พบสินค้าที่ต้องการลบ")
            return redirect(url_for("products"))

        conn.execute("DELETE FROM supplier_product WHERE product_id = ?", (product_id,))
        conn.execute("DELETE FROM product WHERE product_id = ?", (product_id,))
        conn.commit()
        flash(f"ลบสินค้า {product['product_name']} เรียบร้อย")
    except sqlite3.IntegrityError:
        conn.rollback()
        flash("ไม่สามารถลบสินค้าได้ เพราะสินค้านี้ถูกใช้ในประวัติการขายแล้ว")
    finally:
        conn.close()
    return redirect(url_for("products"))


@app.route("/suppliers")
@login_required
def suppliers():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT supplier_id, supplier_name, phone_number FROM supplier ORDER BY supplier_id"
    ).fetchall()
    conn.close()
    return render_template("suppliers.html", suppliers=rows)


@app.route("/sales")
@login_required
def sales():
    conn = get_db_connection()
    sale_rows = conn.execute(
        """
        SELECT s.sale_id, s.sale_date, c.customer_name, e.employee_name, s.total_amount
        FROM sale s
        JOIN customer c ON c.customer_id = s.customer_id
        JOIN employee e ON e.employee_id = s.employee_id
        ORDER BY s.sale_id DESC
        """
    ).fetchall()
    sale_details = conn.execute(
        """
        SELECT sd.sale_id, p.product_name, p.model, p.brand, sd.qty, sd.unit_price,
               (sd.qty * sd.unit_price) AS line_total,
               CASE p.brand
                   WHEN 'Apple' THEN '6.1 นิ้ว'
                   WHEN 'Samsung' THEN '6.8 นิ้ว'
                   WHEN 'Redmi' THEN '6.67 นิ้ว'
                   ELSE 'มาตรฐาน'
               END AS screen_size,
               CASE p.brand
                   WHEN 'Apple' THEN '256 GB'
                   WHEN 'Samsung' THEN '256 GB'
                   WHEN 'Redmi' THEN '512 GB'
                   ELSE 'ไม่ระบุ'
               END AS storage_capacity,
               CASE p.brand
                   WHEN 'Apple' THEN '8 GB'
                   WHEN 'Samsung' THEN '12 GB'
                   WHEN 'Redmi' THEN '12 GB'
                   ELSE 'ไม่ระบุ'
               END AS ram,
               CASE p.brand
                   WHEN 'Apple' THEN 'Natural Titanium'
                   WHEN 'Samsung' THEN 'Titanium Black'
                   WHEN 'Redmi' THEN 'Midnight Black'
                   ELSE 'ไม่ระบุ'
               END AS phone_color
        FROM sale_detail sd
        JOIN product p ON p.product_id = sd.product_id
        ORDER BY sd.sale_id DESC
        """
    ).fetchall()
    conn.close()
    return render_template("sales.html", sales=sale_rows, sale_details=sale_details)


@app.route("/sales/edit")
@login_required
def choose_sale_to_edit():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT s.sale_id, s.sale_date, c.customer_name FROM sale s JOIN customer c ON c.customer_id = s.customer_id ORDER BY s.sale_id DESC"
    ).fetchall()
    conn.close()
    return render_template("choose_sale_edit.html", sales=rows)


@app.route("/sales/<int:sale_id>/edit", methods=["GET", "POST"])
@login_required
def edit_sale(sale_id):
    conn = get_db_connection()
    sale = conn.execute("SELECT sale_id, customer_id, employee_id FROM sale WHERE sale_id = ?", (sale_id,)).fetchone()
    customers = conn.execute("SELECT customer_id, customer_name FROM customer ORDER BY customer_id").fetchall()
    employees = conn.execute("SELECT employee_id, employee_name FROM employee ORDER BY employee_id").fetchall()
    products = conn.execute("SELECT product_id, product_name, price, stock_qty FROM product ORDER BY product_id").fetchall()
    detail = conn.execute("SELECT product_id, qty FROM sale_detail WHERE sale_id = ?", (sale_id,)).fetchone()
    if not sale or not detail:
        conn.close()
        flash("ไม่พบรายการขายที่ต้องการแก้ไข")
        return redirect(url_for("sales"))

    if request.method == "POST":
        customer_id = int(request.form.get("customer_id") or 0)
        employee_id = int(request.form.get("employee_id") or 0)
        product_id = int(request.form.get("product_id") or 0)
        qty = int(request.form.get("qty") or 0)
        old_product_id, old_qty = detail[0], detail[1]
        old_product = conn.execute("SELECT price FROM product WHERE product_id = ?", (old_product_id,)).fetchone()
        new_product = conn.execute("SELECT price, stock_qty FROM product WHERE product_id = ?", (product_id,)).fetchone()
        available_stock = (new_product[1] if product_id != old_product_id else new_product[1] + old_qty) if new_product else 0
        if not customer_id or not employee_id or not new_product or qty <= 0 or qty > available_stock:
            conn.close()
            flash("ข้อมูลการขายไม่ถูกต้องหรือสต็อกไม่เพียงพอ")
            return render_template("sale_form.html", customers=customers, employees=employees, products=products, sale=dict(sale), detail=dict(detail), edit_mode=True)

        conn.execute("UPDATE product SET stock_qty = stock_qty + ? WHERE product_id = ?", (old_qty, old_product_id))
        conn.execute("UPDATE product SET stock_qty = stock_qty - ? WHERE product_id = ?", (qty, product_id))
        conn.execute("UPDATE sale SET customer_id = ?, employee_id = ?, total_amount = ? WHERE sale_id = ?", (customer_id, employee_id, qty * new_product[0], sale_id))
        conn.execute("UPDATE sale_detail SET product_id = ?, qty = ?, unit_price = ? WHERE sale_id = ?", (product_id, qty, new_product[0], sale_id))
        conn.commit()
        conn.close()
        flash("แก้ไขข้อมูลการขายเรียบร้อย")
        return redirect(url_for("sales"))

    conn.close()
    return render_template("sale_form.html", customers=customers, employees=employees, products=products, sale=dict(sale), detail=dict(detail), edit_mode=True)


@app.route("/sales/cancel", methods=["GET", "POST"])
@login_required
def cancel_sales():
    conn = get_db_connection()
    if request.method == "POST":
        sale_id = int(request.form.get("sale_id") or 0)
        sale = conn.execute(
            "SELECT sale_id FROM sale WHERE sale_id = ?",
            (sale_id,),
        ).fetchone()
        if not sale:
            flash("ไม่พบรายการขายที่ต้องการยกเลิก")
        else:
            conn.execute("DELETE FROM sale_detail WHERE sale_id = ?", (sale_id,))
            conn.execute("DELETE FROM sale WHERE sale_id = ?", (sale_id,))
            conn.commit()
            flash(f"ยกเลิกรายการขายเลขที่ {sale_id} เรียบร้อย")
        conn.close()
        return redirect(url_for("sales"))

    rows = conn.execute(
        """
        SELECT s.sale_id, s.sale_date, c.customer_name, s.total_amount
        FROM sale s
        JOIN customer c ON c.customer_id = s.customer_id
        ORDER BY s.sale_id DESC
        """
    ).fetchall()
    conn.close()
    return render_template("cancel_sale.html", sales=rows)


@app.route("/sales/new", methods=["GET", "POST"])
@login_required
def add_sale():
    conn = get_db_connection()
    customers = conn.execute("SELECT customer_id, customer_name FROM customer ORDER BY customer_id").fetchall()
    employees = conn.execute("SELECT employee_id, employee_name FROM employee ORDER BY employee_id").fetchall()
    products = conn.execute("SELECT product_id, product_name, price, stock_qty FROM product ORDER BY product_id").fetchall()
    conn.close()

    if request.method == "POST":
        customer_id = int(request.form.get("customer_id") or 0)
        employee_id = int(request.form.get("employee_id") or 0)
        product_id = int(request.form.get("product_id") or 0)
        qty = int(request.form.get("qty") or 0)

        if not customer_id or not employee_id or not product_id or qty <= 0:
            flash("กรุณากรอกข้อมูลการขายให้ครบถ้วน")
            return render_template("sale_form.html", customers=customers, employees=employees, products=products)

        conn = get_db_connection()
        cur = conn.cursor()
        product = cur.execute(
            "SELECT product_name, price, stock_qty FROM product WHERE product_id = ?",
            (product_id,),
        ).fetchone()

        if not product:
            conn.close()
            flash("ไม่พบสินค้า")
            return render_template("sale_form.html", customers=customers, employees=employees, products=products)

        if qty > product["stock_qty"]:
            conn.close()
            flash("จำนวนสินค้าในสต็อกไม่เพียงพอ")
            return render_template("sale_form.html", customers=customers, employees=employees, products=products)

        unit_price = float(product["price"])
        total_amount = qty * unit_price

        cur.execute(
            "INSERT INTO sale (sale_date, customer_id, employee_id, total_amount) VALUES (date('now'), ?, ?, ?)",
            (customer_id, employee_id, total_amount),
        )
        sale_id = cur.lastrowid
        cur.execute(
            "INSERT INTO sale_detail (sale_id, product_id, qty, unit_price) VALUES (?, ?, ?, ?)",
            (sale_id, product_id, qty, unit_price),
        )
        cur.execute(
            "UPDATE product SET stock_qty = stock_qty - ? WHERE product_id = ?",
            (qty, product_id),
        )
        conn.commit()
        conn.close()
        flash("บันทึกการขายเรียบร้อย")
        return redirect(url_for("sales"))

    return render_template("sale_form.html", customers=customers, employees=employees, products=products)


init_db()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)

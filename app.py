import io, csv
from flask import make_response
from flask import (
    Flask,
    render_template_string,
    request,
    redirect,
    session,
    url_for,
    flash,
)
from sqlalchemy import create_engine, Column, Integer, String, Date, ForeignKey, Text, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from datetime import date, datetime, timedelta
from calendar import monthrange

app = Flask(__name__)
MONTHLY_RATE = 1.8334
app.config["SECRET_KEY"] = "dev-secret-change"

# -------------------- DATABASE --------------------
engine = create_engine("sqlite:///vacation.db", echo=False, future=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    pin = Column(String, nullable=False)
    role = Column(String, default="member")
    annual_allowance = Column(Integer, default=0)  # do ta vendosësh ti vetë
    carryover = Column(Integer, default=0)
    first_login = Column(Boolean, default=True)

    vacations = relationship("Vacation", back_populates="user")
    adjustments = relationship("Adjustment", back_populates="user")

    # ---- llogaritje bilanci ----
    def allowance_total(self):
        return (self.annual_allowance or 0) + (self.carryover or 0)

    def taken_days(self, year: int):
        return sum(
            v.days
            for v in self.vacations
            if v.status == "approved" and v.start.year == year
        )

    def pending_days(self, year: int):
        return sum(
            v.days
            for v in self.vacations
            if v.status == "pending" and v.start.year == year
        )

    def adjustments_sum(self, year: int):
        return sum(a.amount for a in self.adjustments if a.when.year == year)

    def remaining(self, year: int):
        return self.allowance_total() + self.adjustments_sum(year) - self.taken_days(
            year
        )


class Vacation(Base):
    __tablename__ = "vacations"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    start = Column(Date, nullable=False)
    end = Column(Date, nullable=False)
    days = Column(Integer, nullable=False)
    note = Column(Text)
    status = Column(String, default="pending")  # pending / approved / denied

    user = relationship("User", back_populates="vacations")


class Adjustment(Base):
    __tablename__ = "adjustments"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    amount = Column(Integer, nullable=False)  # + ose -
    reason = Column(Text)
    when = Column(Date, default=date.today)

    user = relationship("User", back_populates="adjustments")

class Setting(Base):
    __tablename__ = "settings"

    key = Column(String, primary_key=True)
    value = Column(String)

Base.metadata.create_all(engine)


# -------------------- HELPERS --------------------
def get_current_user():
    uid = session.get("uid")
    if not uid:
        return None
    db = SessionLocal()
    user = db.get(User, uid)
    db.close()
    return user

def get_theme():
    return session.get("theme", "light")

def days_between_calendar(start: date, end: date) -> int:
    """Ditë kalendarike, përfshirë të dyja skajet."""
    if end < start:
        start, end = end, start
    return (end - start).days + 1

def maybe_run_monthly_accrual(db):
    """Nëse nuk është bërë akumulimi për këtë muaj, shton +MONTHLY_RATE për të gjithë user-at."""
    today = date.today()
    month_key = f"accrual_{today.year}_{today.month:02d}"

    existing = db.query(Setting).filter_by(key=month_key).first()
    if existing:
        return  # ky muaj është bërë

    users = db.query(User).all()
    for u in users:
        adj = Adjustment(
            user_id=u.id,
            amount=MONTHLY_RATE,
            reason=f"Akumulim mujor {today.strftime('%Y-%m')}",
            when=date(today.year, today.month, 1),
        )
        db.add(adj)

    db.add(Setting(key=month_key, value=str(today)))
    db.commit()

# -------------------- ROUTES --------------------
@app.route("/")
def index():
    user = get_current_user()
    if user:
        return redirect(url_for("me"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").lower()
        pin = request.form.get("pin", "")

        db = SessionLocal()
        user = db.query(User).filter(User.email == email).first()
        db.close()

        if user and user.pin == pin:
            if user.first_login:
                session["uid"]=user.id
                return redirect(url_for("force_change_pin"))
            session["uid"] = user.id
            flash("Hyrja me sukses!", "success")
            if user.role == "admin":
                return redirect(url_for("admin_dashboard"))
            return redirect(url_for("me"))
        else:
            flash("Email ose PIN i gabuar!", "danger")

    return render_template_string(
        """
<!doctype html>
<html lang="sq">
<head>
  <meta charset="utf-8">
  <title>Vacation Planner – Hyrje</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: radial-gradient(circle at top left, #4f46e5, #111827);
      display: flex;
      align-items: center;
      justify-content: center;
      color: #111827;
    }
    .card {
      background: #f9fafb;
      border-radius: 18px;
      padding: 28px 26px 22px;
      width: 100%;
      max-width: 380px;
      box-shadow: 0 20px 40px rgba(15, 23, 42, .6);
    }
    .logo {
      font-weight: 700;
      font-size: 18px;
      letter-spacing: .08em;
      text-transform: uppercase;
      color: #111827;
      margin-bottom: 6px;
    }
    h2 {
      margin: 0 0 4px;
      font-size: 22px;
      font-weight: 650;
    }
    .subtitle {
      font-size: 13px;
      color: #6b7280;
      margin-bottom: 18px;
    }
    label {
      display: block;
      font-size: 13px;
      color: #4b5563;
      margin-bottom: 4px;
    }
    input {
      width: 100%;
      padding: 9px 11px;
      border-radius: 11px;
      border: 1px solid #d1d5db;
      font-size: 14px;
      margin-bottom: 12px;
      outline: none;
      transition: 0.15s;
      background: #fdfdfd;
    }
    input:focus {
      border-color: #4f46e5;
      box-shadow: 0 0 0 1px rgba(79,70,229,.25);
      background: #ffffff;
    }
    .btn {
      width: 100%;
      border: none;
      border-radius: 999px;
      padding: 9px 0;
      font-size: 14px;
      font-weight: 600;
      background: linear-gradient(90deg, #4f46e5, #2563eb);
      color: #f9fafb;
      cursor: pointer;
      margin-top: 4px;
      transition: 0.15s;
    }
    .btn:hover {
      filter: brightness(1.05);
      transform: translateY(-1px);
      box-shadow: 0 6px 18px rgba(37, 99, 235, .35);
    }
    .flash {
      font-size: 13px;
      padding: 8px 10px;
      border-radius: 10px;
      margin-bottom: 10px;
    }
    .flash-err {
      background: #fee2e2;
      color: #b91c1c;
      border: 1px solid #fecaca;
    }
    .flash-ok {
      background: #dcfce7;
      color: #166534;
      border: 1px solid #bbf7d0;
    }
    .footer {
      margin-top: 10px;
      font-size: 11px;
      color: #9ca3af;
      text-align: center;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="logo">VACATION PLANNER</div>
    <h2>Mirë se erdhe 👋</h2>
    <div class="subtitle">Hyr me email-in dhe PIN-in tënd.</div>

    {% with messages = get_flashed_messages(with_categories=true) %}
      {% for cat, msg in messages %}
        <div class="flash {{ 'flash-ok' if cat == 'success' else 'flash-err' }}">{{ msg }}</div>
      {% endfor %}
    {% endwith %}

    <form method="post">
      <label for="email">Email</label>
      <input id="email" name="email" type="email" autocomplete="username">

      <label for="pin">PIN</label>
      <input id="pin" name="pin" type="password" autocomplete="current-password">

      <button class="btn" type="submit">Hyr</button>
    </form>

    <div class="footer">
      Admin krijon llogaritë dhe përcakton balancën e pushimeve.
    </div>
  </div>
</body>
</html>
    """
    )



@app.route("/me", methods=["GET", "POST"])
def me():
    user = get_current_user()
    if not user:
        return redirect(url_for("login"))

    db = SessionLocal()
    maybe_run_monthly_accrual(db)
    user = db.get(User, user.id)  # rifresko nga DB

    # POST = kërkesë e re pushimi
    if request.method == "POST":
        start_str = request.form.get("start")
        end_str = request.form.get("end")
        note = request.form.get("note") or ""

        try:
            start = datetime.strptime(start_str, "%Y-%m-%d").date()
            end = datetime.strptime(end_str, "%Y-%m-%d").date()
        except Exception:
            flash("Datë e pavlefshme.", "danger")
            db.close()
            return redirect(url_for("me"))

        days = days_between_calendar(start, end)

        vac = Vacation(
            user_id=user.id,
            start=start,
            end=end,
            days=days,
            note=note,
            status="pending",
        )
        db.add(vac)
        db.commit()
        flash(f"Kërkesa u dërgua: {days} ditë.", "success")
        db.close()
        return redirect(url_for("me"))

    # GET = shfaq view personale
    year = date.today().year
    vacations = (
        db.query(Vacation)
        .filter(Vacation.user_id == user.id)
        .order_by(Vacation.start.desc())
        .all()
    )

    allowance = user.allowance_total()
    taken = user.taken_days(year)
    pending = user.pending_days(year)
    adjust = user.adjustments_sum(year)
    remaining = user.remaining(year)

    db.close()

    return render_template_string(
        """
<!doctype html>
<html lang="sq">
<head>
  <meta charset="utf-8">
  <title>Vacation Planner - Profili im</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    * { box-sizing: border-box; }
    :root {
      --bg: #f3f4f6;
      --card: #ffffff;
      --text-main: #111827;
      --text-muted: #6b7280;
      --header-bg: #111827;
      --header-text: #ffffff;
    }
    body.dark {
      --bg: #020617;
      --card: #020617;
      --text-main: #e5e7eb;
      --text-muted: #9ca3af;
      --header-bg: #020617;
      --header-text: #e5e7eb;
    }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--text-main);
    }
    header {
      background: var(--header-bg);
      color: var(--header-text);
      padding: 12px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    header .title {
      font-weight: 600;
      letter-spacing: .03em;
    }
    header a {
      color: #e5e7eb;
      text-decoration: none;
      margin-left: 12px;
      font-size: 14px;
    }
    .container {
      max-width: 1000px;
      margin: 20px auto;
      padding: 0 16px 32px;
    }
    .flash {
      padding: 10px 12px;
      border-radius: 8px;
      margin-bottom: 12px;
      font-size: 14px;
    }
    .flash-ok { background: #dcfce7; color: #166534; }
    .flash-err { background: #fee2e2; color: #b91c1c; }
    .grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0,1fr));
      gap: 12px;
      margin-bottom: 18px;
    }
    .stat {
      background: #fff;
      border-radius: 14px;
      padding: 10px 14px;
      box-shadow: 0 4px 12px rgba(15, 23, 42, .06);
    }
    .stat-label { font-size: 12px; color: #6b7280; }
    .stat-value { font-size: 20px; font-weight: 600; margin-top: 4px; }
    .card {
      background: #fff;
      border-radius: 14px;
      padding: 18px 18px 14px;
      box-shadow: 0 4px 14px rgba(15, 23, 42, .08);
      margin-bottom: 18px;
    }
    h2, h3 {
      margin: 0 0 12px;
      font-weight: 600;
      color: #111827;
    }
    form label {
      font-size: 13px;
      color: #4b5563;
    }
    form input, form textarea, form select {
      width: 100%;
      padding: 8px 10px;
      border-radius: 10px;
      border: 1px solid #e5e7eb;
      font-size: 14px;
      margin-top: 4px;
    }
    form textarea { resize: vertical; min-height: 60px; }
    .form-row {
      display: grid;
      grid-template-columns: repeat(2, minmax(0,1fr));
      gap: 12px;
    }
    .btn {
      display: inline-block;
      padding: 8px 16px;
      border-radius: 999px;
      border: none;
      background: #111827;
      color: #fff;
      font-size: 14px;
      cursor: pointer;
      margin-top: 10px;
    }
    .btn-secondary {
      background: #4b5563;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      padding: 8px 10px;
      border-bottom: 1px solid #e5e7eb;
      text-align: left;
    }
    th {
      background: #f9fafb;
      font-weight: 600;
      color: #374151;
    }
    .status {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 11px;
      font-weight: 500;
    }
    .st-approved { background: #dcfce7; color: #166534; }
    .st-pending { background: #fef3c7; color: #92400e; }
    .st-denied  { background: #fee2e2; color: #b91c1c; }
  </style>
</head>
<body class = "{{ theme }}">
<header>
  <div class="title">Vacation Planner</div>
  <div>
    <span style="font-size:14px; margin-right:8px;">{{ user.name }}</span>
     <a href="{{ url_for('toggle_theme') }}">Tema: {{ 'Dark' if theme == 'light' else 'Light' }}</a>
    <a href="{{ url_for('admin_dashboard') }}">Admin</a>
    <a href="{{ url_for('logout') }}">Dil</a>
  </div>
</header>
<div class="container">

  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for cat, msg in messages %}
      <div class="flash {{ 'flash-ok' if cat == 'success' else 'flash-err' }}">{{ msg }}</div>
    {% endfor %}
  {% endwith %}

  <h2>Profili im – {{ year }}</h2>

  <div class="grid">
    <div class="stat">
      <div class="stat-label">Leje + carryover</div>
      <div class="stat-value">{{ allowance }}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Rregullime (±)</div>
      <div class="stat-value">{{ adjust }}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Të marra (approved)</div>
      <div class="stat-value">{{ taken }}</div>
    </div>
    <div class="stat">
      <div class="stat-label">Të mbetura</div>
      <div class="stat-value">{{ remaining }}</div>
    </div>
  </div>

  <div class="card">
    <h3>Kërko pushim (ditë kalendarike)</h3>
    <form method="post">
      <div class="form-row">
        <div>
          <label>Data fillimit</label>
          <input type="date" name="start" required>
        </div>
        <div>
          <label>Data e fundit</label>
          <input type="date" name="end" required>
        </div>
      </div>
      <div style="margin-top:10px;">
        <label>Shënim (opsional)</label>
        <textarea name="note"></textarea>
      </div>
      <button class="btn" type="submit">Dërgo kërkesë</button>
    </form>
  </div>

  <div class="card">
    <h3>Kërkesat e mia</h3>
    <table>
      <tr>
        <th>Data</th>
        <th>Ditë</th>
        <th>Status</th>
        <th>Shënim</th>
      </tr>
      {% for v in vacations %}
      <tr>
        <td>{{ v.start }} → {{ v.end }}</td>
        <td>{{ v.days }}</td>
        <td>
          {% if v.status == 'approved' %}
            <span class="status st-approved">Aprovuar</span>
          {% elif v.status == 'pending' %}
            <span class="status st-pending">Në pritje</span>
          {% else %}
            <span class="status st-denied">Refuzuar</span>
          {% endif %}
        </td>
        <td>{{ v.note }}</td>
      </tr>
      {% endfor %}
    </table>
  </div>

</div>
</body>
</html>
    """,
        user=user,
        year=year,
        allowance=allowance,
        adjust=adjust,
        taken=taken,
        pending=pending,
        remaining=remaining,
        vacations=vacations,
        theme = get_theme(),
    )

@app.route("/admin")
def admin_dashboard():
    user = get_current_user()
    if not user or user.role != "admin":
        return redirect(url_for("login"))

    db = SessionLocal()
    maybe_run_monthly_accrual(db)
    year = date.today().year

    users = db.query(User).all()
    vacations = db.query(Vacation).order_by(Vacation.start.desc()).all()

    # rreshtat për tabelën e ekipit
    rows = []
    for u in users:
        rows.append(
            dict(
                id=u.id,
                name=u.name,
                email=u.email,
                allowance=u.allowance_total(),
                adjust=u.adjustments_sum(year),
                taken=u.taken_days(year),
                pending=u.pending_days(year),
                remaining=u.remaining(year),
            )
        )

    # rreshtat për tabelën e pushimeve
    vac_rows = []
    for v in vacations:
        vac_rows.append(
            dict(
                id=v.id,
                user_name=v.user.name,
                user_email=v.user.email,
                start=v.start,
                end=v.end,
                days=v.days,
                status=v.status,
            )
        )

    db.close()

    return render_template_string(
        """
<!doctype html>
<html lang="sq">
<head>
  <meta charset="utf-8">
  <title>Vacation Planner - Admin</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f3f4f6;
      color: #111827;
    }
    header {
      background: #111827;
      color: #fff;
      padding: 12px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    header .title {
      font-weight: 600;
      letter-spacing: .03em;
    }
    header a {
      color: #e5e7eb;
      text-decoration: none;
      margin-left: 12px;
      font-size: 14px;
    }
    .container {
      max-width: 1200px;
      margin: 20px auto;
      padding: 0 16px 32px;
    }
    .flash {
      padding: 10px 12px;
      border-radius: 8px;
      margin-bottom: 12px;
      font-size: 14px;
      background: #dcfce7;
      color: #166534;
    }
    h2, h3 {
      margin: 0 0 12px;
      font-weight: 600;
      color: #111827;
    }
    .toolbar a {
      display: inline-block;
      padding: 6px 12px;
      border-radius: 999px;
      background: #111827;
      color: #fff;
      text-decoration: none;
      font-size: 13px;
      margin-right: 8px;
    }
    .toolbar a.secondary {
      background: #4b5563;
    }
    .toolbar a.accent {
      background: #2563eb;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(0,1.1fr) minmax(0,1fr);
      gap: 16px;
      margin-top: 10px;
    }
    .card {
      background: #fff;
      border-radius: 14px;
      padding: 16px 16px 12px;
      box-shadow: 0 4px 14px rgba(15, 23, 42, .08);
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      padding: 8px 10px;
      border-bottom: 1px solid #e5e7eb;
      text-align: left;
    }
    th {
      background: #f9fafb;
      font-weight: 600;
      color: #374151;
    }
    .tag {
      display: inline-block;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 11px;
      background: #e5e7eb;
      color: #374151;
    }
    .link-actions a {
      font-size: 12px;
      margin-right: 6px;
      text-decoration: none;
      color: #2563eb;
    }
    .action-btn {
      display: inline-block;
      padding: 5px 10px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 500;
      text-decoration: none;
      margin-right: 6px;
      transition: 0.15s;
    }

    .approve-btn {
      background: #d1fae5;
      color: #065f46;
      border: 1px solid #34d399;
    }
    .approve-btn:hover {
      background: #34d399;
      color: white;
    }

    .deny-btn {
      background: #fef3c7;
      color: #92400e;
      border: 1px solid #fbbf24;
    }
    .deny-btn:hover {
      background: #fbbf24;
      color: white;
    }

    .delete-btn {
      background: #fee2e2;
      color: #b91c1c;
      border: 1px solid #ef4444;
    }
    .delete-btn:hover {
      background: #ef4444;
      color: white;
    }
        .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 4px 10px;
      font-size: 12px;
      font-weight: 600;
      border-radius: 999px;
      width: max-content;
    }

    .status-approved {
      background: #d1fae5;
      color: #065f46;
      border: 1px solid #34d399;
    }

    .status-pending {
      background: #fef9c3;
      color: #854d0e;
      border: 1px solid #facc15;
    }

    .status-denied {
      background: #fee2e2;
      color: #b91c1c;
      border: 1px solid #ef4444;
    }
    .link-actions a.danger { color: #b91c1c; }
  </style>
</head>
<body>
<header>
  <div class="title">Vacation Planner – Admin</div>
  <div>
    <a href="{{ url_for('me') }}">Profili im</a>
    <a href="{{ url_for('admin_report') }}" class="secondary">📊 Raport</a>
    <a href="{{ url_for('admin_export_vacations') }}" class="secondary">⬇ Export CSV</a>
    <a href="{{ url_for('logout') }}">Dil</a>
  </div>
</header>
<div class="container">

  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for cat, msg in messages %}
      <div class="flash">{{ msg }}</div>
    {% endfor %}
  {% endwith %}

  <h2>Pasqyra {{ year }}</h2>
  <div class="toolbar">
    <a href="{{ url_for('admin_create_user') }}" class="secondary">➕ Shto përdorues</a>
    <a href="{{ url_for('admin_calendar') }}" class="secondary">📅 Kalendar pushimesh</a>
  </div>

  <div class="grid">
    <div class="card">
      <h3>Ekipi</h3>
      <table>
        <tr>
          <th>Emri</th>
          <th>Email</th>
          <th>Leje</th>
          <th>±</th>
          <th>Marrë</th>
          <th>Në pritje</th>
          <th>Mbetur</th>
          <th>Edit</th>
        </tr>
        {% for r in rows %}
        <tr>
          <td>{{ r.name }}</td>
          <td>{{ r.email }}</td>
          <td>{{ r.allowance }}</td>
          <td>{{ r.adjust }}</td>
          <td>{{ r.taken }}</td>
          <td>{{ r.pending }}</td>
          <td><strong>{{ r.remaining }}</strong></td>
          <td>
            <a href="{{ url_for('admin_edit_user', uid=r.id) }}"
            style="
            padding:6px 12px;
            background:#111827;
            color:white;
            border-radius:8px;
            text-decoration:none;
            font-size:13px;
            display:inline-block;">
            Edito
            </a>
          </td>
        </tr>
        {% endfor %}
      </table>
    </div>

    <div class="card">
      <h3>Kërkesa pushimi</h3>
      <table>
        <tr>
          <th>Përdoruesi</th>
          <th>Data</th>
          <th>Ditë</th>
          <th>Status</th>
          <th>Veprim</th>
        </tr>
        {% for v in vac_rows %}
        <tr>
          <td>{{ v.user_name }} <span class="tag">{{ v.user_email }}</span></td>
          <td>{{ v.start }} → {{ v.end }}</td>
          <td>{{ v.days }}</td>
          <td>
            {% if v.status == 'approved' %}
            <span class="status-badge status-approved">✔ Aprovuar</span>
            {% elif v.status == 'pending' %}
            <span class="status-badge status-pending">⏳ Në pritje</span>
            {% else %}
            <span class="status-badge status-denied">✖ Refuzuar</span>
            {% endif %}
          </td>
          <td>
             <a href="{{ url_for('admin_vacation_action', vid=v.id, action='approve') }}"
             class="action-btn approve-btn">Aprovo</a>
             <a href="{{ url_for('admin_vacation_action', vid=v.id, action='deny') }}"
             class="action-btn deny-btn">Refuzo</a>
             <a href="{{ url_for('admin_vacation_action', vid=v.id, action='delete') }}"
             class="action-btn delete-btn">Fshi</a>
          </td>
        </tr>
        {% endfor %}
      </table>
    </div>
  </div>

</div>
</body>
</html>
    """,
        rows=rows,
        vac_rows=vac_rows,
        year=year,
    )


@app.route("/admin/vacation/<int:vid>/<string:action>")
def admin_vacation_action(vid, action):
    admin = get_current_user()
    if not admin or admin.role != "admin":
        return redirect(url_for("login"))

    db = SessionLocal()
    v = db.get(Vacation, vid)

    if not v:
        db.close()
        flash("Kërkesa nuk ekziston!", "danger")
        return redirect(url_for("admin_dashboard"))

    if action == "approve":
        v.status = "approved"
    elif action == "deny":
        v.status = "denied"
    elif action == "delete":
        db.delete(v)
        db.commit()
        db.close()
        flash("Kërkesa u fshi!", "success")
        return redirect(url_for("admin_dashboard"))

    db.commit()
    db.close()
    flash("U përditësua me sukses!", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/admin/user/<int:uid>", methods=["GET", "POST"])
def admin_edit_user(uid):
    admin = get_current_user()
    if not admin or admin.role != "admin":
        return redirect(url_for("login"))

    db = SessionLocal()
    u = db.get(User, uid)
    if not u:
        db.close()
        flash("Përdoruesi nuk u gjet.", "danger")
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        days_str = request.form.get("days", "").strip()
        role = (request.form.get("role") or u.role).strip()
        try:
            days = float(days_str)
        except ValueError:
            db.close()
            flash("Vlerë e pavlefshme.", "danger")
            return redirect(url_for("admin_edit_user", uid=uid))
        if role not in ("member", "admin"):
            role = "member"

        u.annual_allowance = days
        u.role = role
        db.commit()
        db.close()
        flash("Ditët dhe roli u perditsuan.", "success")
        return redirect(url_for("admin_dashboard"))

    name = u.name
    email = u.email
    current_days = u.annual_allowance or 0
    current_role = u.role
    db.close()

    return render_template_string("""
<!doctype html>
<html lang="sq">
<head>
  <meta charset="utf-8">
  <title>Edito përdoruesin</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f3f4f6;
      color: #111827;
    }
    header {
      background: #111827;
      color: #fff;
      padding: 12px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    header a { color: #e5e7eb; text-decoration: none; font-size: 14px; }
    .container {
      max-width: 520px;
      margin: 24px auto 32px;
      padding: 0 16px;
    }
    .card {
      background: #fff;
      border-radius: 14px;
      padding: 20px 20px 16px;
      box-shadow: 0 4px 14px rgba(15,23,42,.08);
    }
    h2 { margin: 0 0 6px; }
    .subtitle {
      font-size: 13px;
      color: #6b7280;
      margin-bottom: 16px;
    }
    label {
      display: block;
      font-size: 13px;
      color: #4b5563;
      margin-bottom: 4px;
    }
    input, select {
      width: 100%;
      padding: 9px 10px;
      border-radius: 10px;
      border: 1px solid #d1d5db;
      font-size: 14px;
      margin-bottom: 12px;
    }
    input[disabled] {
      background: #f9fafb;
      color: #6b7280;
    }
    button {
      border: none;
      border-radius: 999px;
      padding: 9px 18px;
      font-size: 14px;
      font-weight: 500;
      background: #111827;
      color: #fff;
      cursor: pointer;
      margin-top: 4px;
    }
  </style>
</head>
<body>
<header>
  <div>Vacation Planner – Admin</div>
  <a href="{{ url_for('admin_dashboard') }}">⬅ Kthehu te admin</a>
</header>

<div class="container">
  <div class="card">
    <h2>Edito përdoruesin</h2>
    <div class="subtitle">Ndrysho rolin ose lejen vjetore për këtë përdorues.</div>

    <form method="post">
      <label>Emri</label>
      <input type="text" value="{{ name }}" disabled>

      <label>Email</label>
      <input type="text" value="{{ email }}" disabled>

      <label>Roli</label>
      <select name="role">
        <option value="member" {% if current_role == 'member' %}selected{% endif %}>Member</option>
        <option value="admin" {% if current_role == 'admin' %}selected{% endif %}>Admin</option>
      </select>

      <label>Leje vjetore (ditë)</label>
      <input type="number" step="0.0001" name="days" value="{{ current_days }}">

      <button type="submit">Ruaj ndryshimet</button>
    </form>
    <div style="margin-top:18px; padding-top:12px; border-top:1px solid #e5e7eb;">
      <div style="font-size:13px; color:#b91c1c; font-weight:600; margin-bottom:6px;">
        Zona e rrezikshme
      </div>
      <form method="post" action="{{ url_for('admin_delete_user', uid=uid) }}">
        <button type="submit"
                onclick="return confirm('Je i sigurt që do ta fshish këtë përdorues? Kjo veprim është i pakthyeshëm.');"
                style="padding:8px 14px; border-radius:999px; border:none; background:#b91c1c; color:white; font-size:13px; cursor:pointer;">
          Fshi përdoruesin
        </button>
      </form>
      <form method="post" action="{{ url_for('admin_reset_pin', uid=uid) }}" style="margin-top:10px;">
       <button type="submit"
          style="padding:8px 14px; border-radius:999px; background:#2563eb; color:white; border:none; cursor:pointer;">
          Reset PIN
       </button>
      </form>
    </div>
  </div>
</div>
</body>
</html>
    """, name=name,
        email=email,
        current_days=current_days,
        current_role=current_role,
        uid=uid
        )


@app.route("/admin/users/new", methods=["GET", "POST"])
def admin_create_user():
    admin = get_current_user()
    if not admin or admin.role != "admin":
        return redirect(url_for("login"))

    db = SessionLocal()

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        pin = (request.form.get("pin") or "").strip()
        days_str = (request.form.get("days") or "").strip()
        role = (request.form.get("role") or "member").strip()
        if role not in ("member", "admin"):
            role = "member"

        # validime të thjeshta
        if not name or not email or not pin:
            db.close()
            flash("Emri, email dhe PIN janë të detyrueshme.", "danger")
            return redirect(url_for("admin_create_user"))

        try:
            days = float(days_str) if days_str else 0.0
        except ValueError:
            db.close()
            flash("Vlerë e pavlefshme për ditët.", "danger")
            return redirect(url_for("admin_create_user"))

        # kontrollo nëse ekziston email
        existing = db.query(User).filter(User.email == email).first()
        if existing:
            db.close()
            flash("Ekziston tashmë një përdorues me këtë email.", "danger")
            return redirect(url_for("admin_create_user"))

        u = User(
            name=name,
            email=email,
            pin=pin,
            role=role,
            annual_allowance=days,
            carryover=0,
            first_login=True,
        )
        db.add(u)
        db.commit()
        db.close()
        flash("Përdoruesi u krijua me sukses.", "success")
        return redirect(url_for("admin_dashboard"))

    db.close()
    return render_template_string("""
<!doctype html>
<html lang="sq">
<head>
  <meta charset="utf-8">
  <title>Shto përdorues</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f3f4f6;
      color: #111827;
    }
    header {
      background: #111827;
      color: #fff;
      padding: 12px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    header a { color: #e5e7eb; text-decoration: none; font-size: 14px; }
    .container {
      max-width: 520px;
      margin: 24px auto 32px;
      padding: 0 16px;
    }
    .card {
      background: #fff;
      border-radius: 14px;
      padding: 20px 20px 16px;
      box-shadow: 0 4px 14px rgba(15,23,42,.08);
    }
    h2 { margin: 0 0 14px; }
    label {
      display: block;
      font-size: 13px;
      color: #4b5563;
      margin-bottom: 4px;
    }
    input {
      width: 100%;
      padding: 8px 10px;
      border-radius: 10px;
      border: 1px solid #d1d5db;
      font-size: 14px;
      margin-bottom: 12px;
    }
    button {
      border: none;
      border-radius: 999px;
      padding: 8px 18px;
      font-size: 14px;
      font-weight: 500;
      background: #111827;
      color: #fff;
      cursor: pointer;
      margin-top: 4px;
    }
    .flash {
      padding: 8px 10px;
      border-radius: 10px;
      margin-bottom: 10px;
      font-size: 13px;
      background: #fee2e2;
      color: #b91c1c;
    }
  </style>
</head>
<body>
<header>
  <div>Vacation Planner – Admin</div>
  <a href="{{ url_for('admin_dashboard') }}">⬅ Kthehu te admin</a>
</header>

<div class="container">
  <div class="card">
    <h2>Shto përdorues të ri</h2>

    {% with messages = get_flashed_messages(with_categories=true) %}
      {% for cat, msg in messages %}
        <div class="flash">{{ msg }}</div>
      {% endfor %}
    {% endwith %}

    <form method="post">
      <label>Emri</label>
      <input type="text" name="name" required>

      <label>Email</label>
      <input type="email" name="email" required>

      <label>PIN (p.sh. 4 shifra)</label>
      <input type="text" name="pin" required>
      
      <label>Roli</label>
      <select name="role" style="width:100%; padding:8px 10px; border-radius:10px; border:1px solid #d1d5db; font-size:14px; margin-bottom:12px;">
        <option value="member">Member</option>
        <option value="admin">Admin</option>
      </select>

      <label>Ditë aktuale pushimi (balanca sot)</label>
      <input type="number" step="0.0001" name="days">

      <button type="submit">Krijo përdorues</button>
    </form>
  </div>
</div>
</body>
</html>F
    """)


@app.route("/admin/calendar")
def admin_calendar():
    admin = get_current_user()
    if not admin or admin.role != "admin":
        return redirect(url_for("login"))

    db = SessionLocal()
    today = date.today()

    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))

    first_day = date(year, month, 1)
    last_day_num = monthrange(year, month)[1]
    last_day = date(year, month, last_day_num)

    vacations = (
        db.query(Vacation)
        .filter(
            Vacation.status.in_(["approved", "pending"]),
            Vacation.start <= last_day,
            Vacation.end >= first_day,
        )
        .all()
    )

    approved_counts = [0] * (last_day_num + 1)
    pending_counts = [0] * (last_day_num + 1)
    people_by_day = [[] for _ in range(last_day_num + 1)]

    for v in vacations:
        start_d = max(v.start, first_day)
        end_d = min(v.end, last_day)
        d = start_d
        while d <= end_d:
            idx = d.day
            if v.status == "approved":
                approved_counts[idx] += 1
                label = f"{v.user.name}"
            else:
                pending_counts[idx] += 1
                label = f"{v.user.name} (pending)"
            people_by_day[idx].append(label)
            d += timedelta(days=1)

    db.close()

    # emrat e ditëve të javës (0 = e hënë)
    weekday_names = ["Hënë", "Martë", "Mërkurë", "Enjte", "Premte", "Shtunë", "Diel"]

    rows = []
    for day in range(1, last_day_num + 1):
        dt = date(year, month, day)
        weekday = weekday_names[dt.weekday()]
        rows.append(
            dict(
                day=day,
                weekday=weekday,
                approved=approved_counts[day],
                pending=pending_counts[day],
                people=people_by_day[day],
            )
        )

    return render_template_string(
        """
<!doctype html>
<html lang="sq">
<head>
  <meta charset="utf-8">
  <title>Kalendar pushimesh</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f3f4f6;
      color: #111827;
    }
    header {
      background: #111827;
      color: #fff;
      padding: 12px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    header a {
      color: #e5e7eb;
      text-decoration: none;
      font-size: 14px;
    }
    .container {
      max-width: 800px;
      margin: 20px auto 32px;
      padding: 0 16px;
    }
    .card {
      background: #fff;
      border-radius: 14px;
      padding: 18px 18px 14px;
      box-shadow: 0 4px 14px rgba(15, 23, 42, .08);
    }
    h2 {
      margin: 0 0 12px;
      font-weight: 600;
    }
    form {
      display: flex;
      gap: 8px;
      align-items: center;
      margin-bottom: 14px;
      flex-wrap: wrap;
      font-size: 13px;
    }
    form input {
      padding: 6px 8px;
      border-radius: 10px;
      border: 1px solid #d1d5db;
      font-size: 13px;
      width: 90px;
    }
    form button {
      padding: 6px 12px;
      border-radius: 999px;
      border: none;
      background: #111827;
      color: #fff;
      font-size: 13px;
      cursor: pointer;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
    }
    th, td {
      padding: 8px 10px;
      border-bottom: 1px solid #e5e7eb;
      text-align: left;
      vertical-align: top;
    }
    th {
      background: #f9fafb;
      font-weight: 600;
      color: #374151;
    }
    .pill {
      display: inline-block;
      min-width: 24px;
      text-align: center;
      padding: 2px 8px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 500;
    }
    .pill-ok { background: #dcfce7; color: #166534; }
    .pill-warn { background: #fef3c7; color: #92400e; }
    .pill-hot { background: #fee2e2; color: #b91c1c; }
    .people-list div {
      font-size: 12px;
      color: #374151;
    }
  </style>
</head>
<body>
<header>
  <div>Kalendar pushimesh</div>
  <a href="{{ url_for('admin_dashboard') }}">⬅ Kthehu te admin</a>
</header>

<div class="container">
  <div class="card">
    <h2>{{ month }}/{{ year }}</h2>

    <form method="get">
      <span>Muaji</span>
      <input type="number" name="month" min="1" max="12" value="{{ month }}">
      <span>Viti</span>
      <input type="number" name="year" value="{{ year }}">
      <button type="submit">Shfaq</button>
    </form>

    <table>
      <tr>
        <th>Dita</th>
        <th>Dita e javës</th>
        <th>Me pushim (approved)</th>
        <th>Në pritje</th>
        <th>Emrat</th>
      </tr>
      {% for r in rows %}
        {% set total = r.approved %}
        {% if total == 0 %}
          {% set cls = 'pill-ok' %}
        {% elif total <= 2 %}
          {% set cls = 'pill-warn' %}
        {% else %}
          {% set cls = 'pill-hot' %}
        {% endif %}
      <tr>
        <td>{{ r.day }}</td>
        <td>{{ r.weekday }}</td>
        <td><span class="pill {{ cls }}">{{ r.approved }}</span></td>
        <td>{{ r.pending }}</td>
        <td class="people-list">
          {% if r.people %}
            {% for p in r.people %}
              <div>{{ p }}</div>
            {% endfor %}
          {% else %}
            -
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </table>
  </div>
</div>
</body>
</html>
    """,
        year=year,
        month=month,
        rows=rows,
    )
@app.route("/toggle-theme")
def toggle_theme():
    current = session.get("theme", "light")
    session["theme"] = "dark" if current == "light" else "light"
    # kthehu te faqja e mëparshme
    ref = request.headers.get("Referer") or url_for("me")
    return redirect(ref)

@app.route("/admin/report")
def admin_report():
    admin = get_current_user()
    if not admin or admin.role != "admin":
        return redirect(url_for("login"))

    db = SessionLocal()
    today = date.today()
    year = int(request.args.get("year", today.year))

    vacations = (
        db.query(Vacation)
        .filter(
            Vacation.status == "approved",
            Vacation.start <= date(year, 12, 31),
            Vacation.end >= date(year, 1, 1),
        )
        .all()
    )

    month_days = [0] * 13  # 1-12
    per_user = {}

    # gjithçka llogaritet sa kohë db është hapur
    for v in vacations:
        d = max(v.start, date(year, 1, 1))
        end_d = min(v.end, date(year, 12, 31))
        while d <= end_d:
            if d.year == year:
                month_days[d.month] += 1
                key = v.user.name
                per_user[key] = per_user.get(key, 0) + 1
            d += timedelta(days=1)

    db.close()

    labels_months = [str(m) for m in range(1, 13)]
    data_months = [month_days[m] for m in range(1, 13)]

    user_labels = list(per_user.keys())
    user_data = [per_user[name] for name in user_labels]

    return render_template_string(
        """
<!doctype html>
<html lang="sq">
<head>
  <meta charset="utf-8">
  <title>Raport pushimesh</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    body {
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f3f4f6;
      color: #111827;
    }
    header {
      background: #111827;
      color: #fff;
      padding: 12px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    header a { color: #e5e7eb; text-decoration: none; font-size: 14px; }
    .container {
      max-width: 1000px;
      margin: 20px auto 32px;
      padding: 0 16px;
    }
    .card {
      background: #fff;
      border-radius: 14px;
      padding: 18px 18px 14px;
      box-shadow: 0 4px 14px rgba(15,23,42,.08);
      margin-bottom: 16px;
    }
    h2 { margin: 0 0 12px; }
    form { margin-bottom: 10px; font-size: 13px; }
    input {
      padding: 6px 8px;
      border-radius: 10px;
      border: 1px solid #d1d5db;
      width: 90px;
    }
    button {
      padding: 6px 12px;
      border-radius: 999px;
      border: none;
      background: #111827;
      color: #fff;
      font-size: 13px;
      cursor: pointer;
    }
  </style>
</head>
<body>
<header>
  <div>Raport pushimesh</div>
  <a href="{{ url_for('admin_dashboard') }}">⬅ Kthehu te admin</a>
</header>
<div class="container">
  <div class="card">
    <h2>Viti {{ year }}</h2>
    <form method="get">
      <label>Viti</label>
      <input type="number" name="year" value="{{ year }}">
      <button type="submit">Shfaq</button>
    </form>
  </div>

  <div class="card">
    <h3>Dite pushimi per muaj</h3>
    <canvas id="byMonth"></canvas>
  </div>

  <div class="card">
    <h3>Dite pushimi per person</h3>
    <canvas id="byUser"></canvas>
  </div>
</div>

<script>
  const labelsMonths = {{ labels_months|tojson }};
  const dataMonths = {{ data_months|tojson }};
  const labelsUsers = {{ user_labels|tojson }};
  const dataUsers = {{ data_users|tojson }};

  new Chart(document.getElementById('byMonth'), {
    type: 'bar',
    data: {
      labels: labelsMonths,
      datasets: [{
        label: 'Ditë pushimi',
        data: dataMonths,
      }]
    }
  });

  new Chart(document.getElementById('byUser'), {
    type: 'bar',
    data: {
      labels: labelsUsers,
      datasets: [{
        label: 'Ditë pushimi',
        data: dataUsers,
      }]
    },
    options: {
      indexAxis: 'y'
    }
  });
</script>
</body>
</html>
        """,
        year=year,
        labels_months=labels_months,
        data_months=data_months,
        user_labels=user_labels,
        data_users=user_data,
    )


@app.route("/admin/export-vacations")
def admin_export_vacations():
    admin = get_current_user()
    if not admin or admin.role != "admin":
        return redirect(url_for("login"))

    db = SessionLocal()
    year = int(request.args.get("year", date.today().year))

    vqs = (
        db.query(Vacation)
        .filter(
            Vacation.start >= date(year, 1, 1),
            Vacation.start <= date(year, 12, 31),
        )
        .order_by(Vacation.start)
        .all()
    )

    # mbledhim të dhënat sa kohë sesioni është hapur
    rows = []
    for v in vqs:
        rows.append(
            dict(
                name=v.user.name,
                email=v.user.email,
                start=v.start.isoformat(),
                end=v.end.isoformat(),
                days=v.days,
                status=v.status,
            )
        )

    db.close()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["User", "Email", "Start", "End", "Days", "Status"])
    for r in rows:
        writer.writerow([r["name"], r["email"], r["start"], r["end"], r["days"], r["status"]])

    resp = make_response(output.getvalue().encode("utf-8-sig"))
    resp.headers["Content-Type"] = "text/csv; charset=utf-8"
    resp.headers["Content-Disposition"] = f"attachment; filename=vacations_{year}.csv"
    return resp

@app.route("/admin/user/<int:uid>/delete", methods=["POST"])
def admin_delete_user(uid):
    admin = get_current_user()
    if not admin or admin.role != "admin":
        return redirect(url_for("login"))

    db = SessionLocal()
    u = db.get(User, uid)
    if not u:
        db.close()
        flash("Përdoruesi nuk u gjet.", "danger")
        return redirect(url_for("admin_dashboard"))

    # mos fshi adminin e fundit
    if u.role == "admin":
        admin_count = db.query(User).filter(User.role == "admin").count()
        if admin_count <= 1:
            db.close()
            flash("Nuk mund të fshish adminin e fundit.", "danger")
            return redirect(url_for("admin_edit_user", uid=uid))

    # opsionale: mos lejo të fshijë veten
    if admin.id == u.id:
        db.close()
        flash("Nuk mund të fshish veten.", "danger")
        return redirect(url_for("admin_edit_user", uid=uid))

    # fshij të dhënat e lidhura (pushime + adjustments)
    db.query(Vacation).filter_by(user_id=uid).delete()
    db.query(Adjustment).filter_by(user_id=uid).delete()

    db.delete(u)
    db.commit()
    db.close()

    flash("Përdoruesi u fshi.", "success")
    return redirect(url_for("admin_dashboard"))

@app.route("/force-change-pin", methods=["GET", "POST"])
def force_change_pin():
    u = get_current_user()
    if not u:
        return redirect(url_for("login"))

    if request.method == "POST":
        new_pin = request.form.get("pin", "").strip()

        if len(new_pin) < 4:
            flash("PIN duhet të ketë të paktën 4 shifra.", "danger")
        else:
            db = SessionLocal()
            user = db.get(User, u.id)
            user.pin = new_pin
            user.first_login = False
            db.commit()
            db.close()

            flash("PIN u ndryshua me sukses.", "success")
            return redirect(url_for("me"))

    return render_template_string(
        """
<!doctype html>
<html lang="sq">
<head>
  <meta charset="utf-8">
  <title>Ndrysho PIN-in</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f3f4f6;
      color: #111827;
    }
    header {
      background: #111827;
      color: #fff;
      padding: 12px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }
    header a { color: #e5e7eb; text-decoration: none; font-size: 14px; }
    .container {
      max-width: 480px;
      margin: 32px auto 40px;
      padding: 0 16px;
    }
    .card {
      background: #fff;
      border-radius: 14px;
      padding: 22px 20px 18px;
      box-shadow: 0 4px 14px rgba(15,23,42,.08);
    }
    h2 { margin: 0 0 8px; }
    .subtitle {
      font-size: 13px;
      color: #6b7280;
      margin-bottom: 18px;
    }
    label {
      display: block;
      font-size: 13px;
      color: #4b5563;
      margin-bottom: 4px;
    }
    input[type="password"] {
      width: 100%;
      padding: 9px 10px;
      border-radius: 10px;
      border: 1px solid #d1d5db;
      font-size: 14px;
      margin-bottom: 14px;
    }
    button {
      border: none;
      border-radius: 999px;
      padding: 9px 18px;
      font-size: 14px;
      font-weight: 500;
      background: #111827;
      color: #fff;
      cursor: pointer;
    }
    .flash {
      font-size: 13px;
      padding: 8px 10px;
      border-radius: 10px;
      margin-bottom: 10px;
    }
    .flash-danger { background:#fee2e2; color:#b91c1c; }
    .flash-success { background:#dcfce7; color:#166534; }
  </style>
</head>
<body>
<header>
  <div>Vacation Planner</div>
  <div style="font-size:14px;">{{ name }}</div>
</header>

<div class="container">
  <div class="card">
    <h2>Ndrysho PIN-in</h2>
    <div class="subtitle">
      Për arsye sigurie, duhet të vendosësh një PIN të ri përpara se të vazhdosh.
    </div>

    {% with messages = get_flashed_messages(with_categories=true) %}
      {% for cat, msg in messages %}
        <div class="flash {{ 'flash-' + cat }}">{{ msg }}</div>
      {% endfor %}
    {% endwith %}

    <form method="post">
      <label>PIN i ri (min. 4 shifra)</label>
      <input type="password" name="pin" required>
      <button type="submit">Ruaj PIN-in</button>
    </form>
  </div>
</div>
</body>
</html>
        """,
        name=u.name,
    )

@app.route("/admin/user/<int:uid>/reset-pin", methods=["POST"])
def admin_reset_pin(uid):
    admin = get_current_user()
    if not admin or admin.role != "admin":
        return redirect(url_for("login"))

    db = SessionLocal()
    u = db.get(User, uid)
    if not u:
        db.close()
        return "User nuk u gjet."

    # vendos PIN të ri random
    import random
    new_pin = str(random.randint(1000, 9999))

    u.pin = new_pin
    u.first_login = True  # detyro ta ndryshojë me hyrjen tjetër

    db.commit()
    db.close()

    return f"PIN u rivendos. PIN i ri i perkohshem: {new_pin}"


if __name__ == "__main__":
    db = SessionLocal()
    if not db.query(User).first():
        admin = User(
            name="Admin",
            email="admin@example.com",
            pin="9999",
            role="admin",
            annual_allowance=0,
            carryover=0,
        )
        member = User(
            name="Test User",
            email="test@example.com",
            pin="1234",
            annual_allowance=0,
            carryover=0,
        )
        db.add_all([admin, member])
        db.commit()
        print("U krijua admin: admin@example.com / PIN=9999")
        print("U krijua member: test@example.com / PIN=1234")
    db.close()

    app.run(host = "0.0.0.0", port= 5000)

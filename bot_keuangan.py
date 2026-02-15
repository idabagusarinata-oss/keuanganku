import os
import psycopg2
import matplotlib.pyplot as plt
from datetime import datetime, timedelta, time, timezone
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import pagesizes
from email.message import EmailMessage
import smtplib

# ================= ENV =================
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID"))
DATABASE_URL = os.environ.get("DATABASE_URL")
EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")

if not DATABASE_URL:
    raise Exception("DATABASE_URL not found!")

# ================= DATABASE =================
conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS pemasukan (
    id SERIAL PRIMARY KEY,
    no_transaksi VARCHAR(50) UNIQUE,
    jumlah BIGINT,
    tanggal DATE
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS pengeluaran (
    id SERIAL PRIMARY KEY,
    no_transaksi VARCHAR(50) UNIQUE,
    keterangan TEXT,
    kategori TEXT,
    jumlah BIGINT,
    merchant TEXT,
    tanggal DATE
)
""")

conn.commit()

# ================= HELPER =================
def validasi_nominal(text):
    if not text.isdigit():
        return None, "❌ Masukkan angka saja tanpa titik/koma."
    jumlah = int(text)
    if jumlah <= 0:
        return None, "❌ Harus lebih dari 0."
    return jumlah, None

def parse_tanggal(text):
    t = text.lower().strip()
    if t == "hari ini":
        return datetime.now().strftime("%Y-%m-%d")
    if t == "kemarin":
        return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return text
    except:
        return None

def generate_no_transaksi(tipe, tanggal):
    prefix = "PMK" if tipe == "pemasukan" else "PNG"
    tahun_bulan = tanggal.replace("-", "")[:6]

    table = "pemasukan" if tipe == "pemasukan" else "pengeluaran"

    cursor.execute(
        f"SELECT COUNT(*) FROM {table} WHERE DATE_TRUNC('month', tanggal) = DATE_TRUNC('month', %s::date)",
        (tanggal,)
    )

    count = cursor.fetchone()[0] + 1
    nomor = str(count).zfill(4)
    return f"{prefix}-{tahun_bulan}-{nomor}"

# ================= BACKUP =================
async def weekly_backup(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%Y-%m-%d")
    filename = f"backup_{now}.sql"

    with open(filename, "w", encoding="utf-8") as f:
        cursor.execute("SELECT * FROM pemasukan")
        for r in cursor.fetchall():
            f.write(f"INSERT INTO pemasukan VALUES {r};\n")

        cursor.execute("SELECT * FROM pengeluaran")
        for r in cursor.fetchall():
            f.write(f"INSERT INTO pengeluaran VALUES {r};\n")

    # Telegram
    await context.bot.send_document(
        chat_id=ADMIN_ID,
        document=open(filename, "rb"),
        caption=f"Backup Mingguan {now} ✅"
    )

    # Email
    msg = EmailMessage()
    msg["Subject"] = f"Backup Database {now}"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = "idabagusarinata@gmail.com"
    msg.set_content("Backup database terlampir.")

    with open(filename, "rb") as f:
        msg.add_attachment(
            f.read(),
            maintype="application",
            subtype="octet-stream",
            filename=filename
        )

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)

    os.remove(filename)

# ================= KEYBOARD =================
keyboard = [
    ["Pemasukan", "Pengeluaran"],
    ["Cek Saldo", "Pengeluaran Terbesar"],
    ["Grafik Kategori", "Export PDF"],
    ["Reset Keuangan"]
]
reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ================= BOT =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot Keuangan Aktif ✅", reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    # RESET
    if text == "Reset Keuangan":
        if user_id != ADMIN_ID:
            await update.message.reply_text("❌ Anda bukan admin.")
            return
        cursor.execute("TRUNCATE pemasukan, pengeluaran RESTART IDENTITY")
        conn.commit()
        await update.message.reply_text("Semua data berhasil direset.")
        return

    # CEK SALDO
    if text == "Cek Saldo":
        cursor.execute("SELECT COALESCE(SUM(jumlah),0) FROM pemasukan")
        pemasukan = cursor.fetchone()[0]
        cursor.execute("SELECT COALESCE(SUM(jumlah),0) FROM pengeluaran")
        pengeluaran = cursor.fetchone()[0]
        saldo = pemasukan - pengeluaran

        await update.message.reply_text(
            f"Pemasukan: Rp {pemasukan:,}\n"
            f"Pengeluaran: Rp {pengeluaran:,}\n"
            f"Saldo: Rp {saldo:,}"
        )
        return

    # PENGELUARAN TERBESAR
    if text == "Pengeluaran Terbesar":
        cursor.execute("""
            SELECT keterangan, jumlah, merchant
            FROM pengeluaran
            ORDER BY jumlah DESC
            LIMIT 1
        """)
        data = cursor.fetchone()
        if data:
            await update.message.reply_text(
                f"{data[0]}\nRp {data[1]:,}\nMerchant: {data[2]}"
            )
        else:
            await update.message.reply_text("Belum ada data.")
        return

    # PEMASUKAN FLOW
    if text == "Pemasukan":
        context.user_data["mode"] = "pm_jumlah"
        await update.message.reply_text("Masukkan nominal:")
        return

    if context.user_data.get("mode") == "pm_jumlah":
        jumlah, error = validasi_nominal(text)
        if error:
            await update.message.reply_text(error)
            return
        context.user_data["jumlah"] = jumlah
        context.user_data["mode"] = "pm_tanggal"
        await update.message.reply_text("Masukkan tanggal (YYYY-MM-DD / hari ini / kemarin)")
        return

    if context.user_data.get("mode") == "pm_tanggal":
        tanggal = parse_tanggal(text)
        if not tanggal:
            await update.message.reply_text("Format salah.")
            return

        no = generate_no_transaksi("pemasukan", tanggal)

        cursor.execute(
            "INSERT INTO pemasukan (no_transaksi,jumlah,tanggal) VALUES (%s,%s,%s)",
            (no, context.user_data["jumlah"], tanggal)
        )
        conn.commit()

        await update.message.reply_text(f"Disimpan ✅\nNo: {no}")
        context.user_data.clear()
        return

    # PENGELUARAN FLOW
    if text == "Pengeluaran":
        context.user_data["mode"] = "pg_ket"
        await update.message.reply_text("Belanja apa?")
        return

    if context.user_data.get("mode") == "pg_ket":
        context.user_data["keterangan"] = text
        context.user_data["mode"] = "pg_kategori"
        await update.message.reply_text("Kategori?")
        return

    if context.user_data.get("mode") == "pg_kategori":
        context.user_data["kategori"] = text
        context.user_data["mode"] = "pg_jumlah"
        await update.message.reply_text("Harga?")
        return

    if context.user_data.get("mode") == "pg_jumlah":
        jumlah, error = validasi_nominal(text)
        if error:
            await update.message.reply_text(error)
            return
        context.user_data["jumlah"] = jumlah
        context.user_data["mode"] = "pg_merchant"
        await update.message.reply_text("Merchant?")
        return

    if context.user_data.get("mode") == "pg_merchant":
        context.user_data["merchant"] = text
        context.user_data["mode"] = "pg_tanggal"
        await update.message.reply_text("Tanggal (YYYY-MM-DD / hari ini / kemarin)")
        return

    if context.user_data.get("mode") == "pg_tanggal":
        tanggal = parse_tanggal(text)
        if not tanggal:
            await update.message.reply_text("Format salah.")
            return

        no = generate_no_transaksi("pengeluaran", tanggal)

        cursor.execute("""
            INSERT INTO pengeluaran
            (no_transaksi,keterangan,kategori,jumlah,merchant,tanggal)
            VALUES (%s,%s,%s,%s,%s,%s)
        """, (
            no,
            context.user_data["keterangan"],
            context.user_data["kategori"],
            context.user_data["jumlah"],
            context.user_data["merchant"],
            tanggal
        ))
        conn.commit()

        await update.message.reply_text(f"Disimpan ✅\nNo: {no}")
        context.user_data.clear()
        return

# ================= RUN =================
app = ApplicationBuilder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# Minggu 00:00 WIB
wib = timezone(timedelta(hours=7))
app.job_queue.run_daily(
    weekly_backup,
    time=time(hour=0, minute=0, tzinfo=wib),
    days=(6,)
)

print("Bot berjalan...")
app.run_polling(drop_pending_updates=True)

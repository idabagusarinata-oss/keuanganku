import psycopg2
import os
import matplotlib.pyplot as plt
from datetime import datetime, time, timezone, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import pagesizes
import smtplib
from email.message import EmailMessage

# ================= ENV =================
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID"))
DATABASE_URL = os.environ.get("DATABASE_URL")
EMAIL_ADDRESS = os.environ.get("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")

conn = psycopg2.connect(DATABASE_URL)
cursor = conn.cursor()

# ================= TABLE =================
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

# ================= VALIDASI =================
def validasi_nominal(text):
    if not text.isdigit():
        return None
    return int(text)

# ================= KEYBOARD =================
keyboard = [
    ["Pemasukan", "Pengeluaran"],
    ["Cek Saldo", "Pengeluaran Terbesar"],
    ["Grafik Kategori", "Export PDF"],
    ["Reset Keuangan"]
]
reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ================= BACKUP =================
async def weekly_backup(context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now().strftime("%Y-%m-%d")
    filename = f"backup_{now}.sql"

    with open(filename, "w") as f:
        cursor.execute("SELECT * FROM pemasukan")
        for r in cursor.fetchall():
            f.write(f"INSERT INTO pemasukan VALUES {r};\n")
        cursor.execute("SELECT * FROM pengeluaran")
        for r in cursor.fetchall():
            f.write(f"INSERT INTO pengeluaran VALUES {r};\n")

    await context.bot.send_document(chat_id=ADMIN_ID, document=open(filename,"rb"))

    msg = EmailMessage()
    msg["Subject"] = f"Backup {now}"
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = "idabagusarinata@gmail.com"
    msg.set_content("Backup database terlampir")
    with open(filename,"rb") as f:
        msg.add_attachment(f.read(), maintype="application", subtype="octet-stream", filename=filename)
    with smtplib.SMTP_SSL("smtp.gmail.com",465) as server:
        server.login(EMAIL_ADDRESS,EMAIL_PASSWORD)
        server.send_message(msg)

    os.remove(filename)

# ================= BOT =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot Aktif ✅", reply_markup=reply_markup)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text

    # RESET
    if text == "Reset Keuangan":
        cursor.execute("TRUNCATE pemasukan, pengeluaran RESTART IDENTITY")
        conn.commit()
        await update.message.reply_text("Data direset.")
        return

    # CEK SALDO
    if text == "Cek Saldo":
        cursor.execute("SELECT COALESCE(SUM(jumlah),0) FROM pemasukan")
        pemasukan = cursor.fetchone()[0]
        cursor.execute("SELECT COALESCE(SUM(jumlah),0) FROM pengeluaran")
        pengeluaran = cursor.fetchone()[0]
        await update.message.reply_text(f"Saldo: Rp {pemasukan-pengeluaran:,}")
        return

    # PENGELUARAN TERBESAR
    if text == "Pengeluaran Terbesar":
        cursor.execute("SELECT keterangan,jumlah FROM pengeluaran ORDER BY jumlah DESC LIMIT 1")
        data = cursor.fetchone()
        if data:
            await update.message.reply_text(f"{data[0]} - Rp {data[1]:,}")
        else:
            await update.message.reply_text("Belum ada data.")
        return

    # GRAFIK
    if text == "Grafik Kategori":
        cursor.execute("SELECT kategori,SUM(jumlah) FROM pengeluaran GROUP BY kategori")
        data = cursor.fetchall()
        if not data:
            await update.message.reply_text("Belum ada data.")
            return
        kategori = [d[0] for d in data]
        total = [d[1] for d in data]
        plt.figure()
        plt.bar(kategori,total)
        plt.savefig("grafik.png")
        plt.close()
        await update.message.reply_photo(photo=open("grafik.png","rb"))
        os.remove("grafik.png")
        return

    # EXPORT PDF
    if text == "Export PDF":
        filename="laporan.pdf"
        doc=SimpleDocTemplate(filename,pagesize=pagesizes.A4)
        elements=[]
        styles=getSampleStyleSheet()
        cursor.execute("SELECT * FROM pengeluaran")
        data=cursor.fetchall()
        table_data=[["No","Keterangan","Kategori","Jumlah","Merchant","Tanggal"]]
        for r in data:
            table_data.append([r[1],r[2],r[3],r[4],r[5],str(r[6])])
        table=Table(table_data)
        table.setStyle(TableStyle([("GRID",(0,0),(-1,-1),1,colors.black)]))
        elements.append(table)
        doc.build(elements)
        await update.message.reply_document(open(filename,"rb"))
        os.remove(filename)
        return

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# Schedule backup Minggu 00:00 WIB
wib = timezone(timedelta(hours=7))
app.job_queue.run_daily(weekly_backup, time=time(hour=0,minute=0,tzinfo=wib), days=(6,))

print("Bot berjalan...")
app.run_polling(drop_pending_updates=True)

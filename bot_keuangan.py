import os
import json
import psycopg2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import pagesizes
import gspread
from google.oauth2.service_account import Credentials

# ================= ENV =================
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID"))
DATABASE_URL = os.environ.get("DATABASE_URL")
GOOGLE_CREDS = os.environ.get("GOOGLE_CREDENTIALS")

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

# ================= GOOGLE SHEET =================
try:
    scope = ["https://www.googleapis.com/auth/spreadsheets",
             "https://www.googleapis.com/auth/drive"]

    creds_dict = json.loads(GOOGLE_CREDS)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)

    spreadsheet = client.open("Monitoring Keuangan")
    sheet_pm = spreadsheet.worksheet("Pemasukan")
    sheet_pg = spreadsheet.worksheet("Pengeluaran")
    sheet_ringkasan = spreadsheet.worksheet("Ringkasan")

    GOOGLE_READY = True
except Exception as e:
    print("Google Init Error:", e)
    GOOGLE_READY = False

# ================= HELPER =================
def parse_tanggal(text):
    today = datetime.now()
    if text.lower() == "hari ini":
        return today.strftime("%Y-%m-%d")
    if text.lower() == "kemarin":
        return (today - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        datetime.strptime(text, "%Y-%m-%d")
        return text
    except:
        return None

def validasi_nominal(text):
    if not text.isdigit():
        return None
    jumlah = int(text)
    if jumlah <= 0:
        return None
    return jumlah

def generate_no(tipe):
    prefix = "PMK" if tipe == "pemasukan" else "PNG"
    now = datetime.now().strftime("%Y%m")
    cursor.execute(f"SELECT COUNT(*) FROM {tipe}")
    count = cursor.fetchone()[0] + 1
    return f"{prefix}-{now}-{str(count).zfill(4)}"

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

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # ================= EXPORT PDF FIX =================
    if text == "Export PDF":
        context.user_data["mode"] = "export"
        await update.message.reply_text("Masukkan bulan (format YYYY-MM)\nContoh: 2026-02")
        return

    if context.user_data.get("mode") == "export":
        try:
            datetime.strptime(text, "%Y-%m")
        except:
            await update.message.reply_text("Format salah. Gunakan YYYY-MM")
            return

        bulan = text
        filename = f"Laporan_Keuangan_{bulan}.pdf"

        try:
            doc = SimpleDocTemplate(filename, pagesize=pagesizes.A4)
            elements = []
            styles = getSampleStyleSheet()

            elements.append(Paragraph(f"LAPORAN KEUANGAN BULAN {bulan}", styles["Title"]))
            elements.append(Spacer(1, 20))

            cursor.execute("""
                SELECT no_transaksi,jumlah,tanggal
                FROM pemasukan
                WHERE TO_CHAR(tanggal,'YYYY-MM')=%s
            """,(bulan,))
            pm = cursor.fetchall()

            cursor.execute("""
                SELECT no_transaksi,keterangan,kategori,jumlah,merchant,tanggal
                FROM pengeluaran
                WHERE TO_CHAR(tanggal,'YYYY-MM')=%s
            """,(bulan,))
            pg = cursor.fetchall()

            total_pm = sum(p[1] for p in pm)
            total_pg = sum(p[3] for p in pg)

            data_pm = [["No","Nominal","Tanggal"]]
            for p in pm:
                data_pm.append([p[0],f"Rp {p[1]:,}",str(p[2])])

            table_pm = Table(data_pm)
            table_pm.setStyle(TableStyle([("GRID",(0,0),(-1,-1),1,colors.black)]))
            elements.append(table_pm)
            elements.append(Spacer(1,20))

            data_pg = [["No","Belanja","Kategori","Nominal","Merchant","Tanggal"]]
            for p in pg:
                data_pg.append([p[0],p[1],p[2],f"Rp {p[3]:,}",p[4],str(p[5])])

            table_pg = Table(data_pg)
            table_pg.setStyle(TableStyle([("GRID",(0,0),(-1,-1),1,colors.black)]))
            elements.append(table_pg)
            elements.append(Spacer(1,20))

            elements.append(Paragraph(f"Total Pemasukan: Rp {total_pm:,}",styles["Normal"]))
            elements.append(Paragraph(f"Total Pengeluaran: Rp {total_pg:,}",styles["Normal"]))
            elements.append(Paragraph(f"Sisa Saldo: Rp {total_pm-total_pg:,}",styles["Normal"]))

            doc.build(elements)

            await update.message.reply_document(open(filename,"rb"))
            os.remove(filename)

        except Exception as e:
            print("PDF Error:", e)
            await update.message.reply_text("Terjadi kesalahan saat membuat PDF.")

        context.user_data.clear()
        return

# ================= RUN =================
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("Bot berjalan...")
app.run_polling(drop_pending_updates=True)

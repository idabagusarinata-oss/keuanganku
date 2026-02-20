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

# ================= GOOGLE SHEETS INIT =================
GOOGLE_READY = False
try:
    scope = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    creds_dict = json.loads(GOOGLE_CREDS)
    creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
    client = gspread.authorize(creds)

    spreadsheet = client.open("Monitoring Keuangan")
    sheet_pm = spreadsheet.worksheet("Pemasukan")
    sheet_pg = spreadsheet.worksheet("Pengeluaran")

    # ================= HEADER PROTECTION =================
    if not sheet_pm.get_all_values():
        sheet_pm.append_row(["No Transaksi", "Nominal", "Tanggal"])

    if not sheet_pg.get_all_values():
        sheet_pg.append_row(["No Transaksi", "Belanja", "Kategori", "Nominal", "Merchant", "Tanggal"])

    GOOGLE_READY = True
    print("Google Sheets Connected ✅")

except Exception as e:
    print("Google Sheets Error:", e)

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

# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot Keuangan Aktif ✅", reply_markup=reply_markup)

# ================= HANDLE =================
async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id

    # ================= RESET =================
    if text == "Reset Keuangan":
        if user_id != ADMIN_ID:
            await update.message.reply_text("❌ Anda bukan admin.")
            return

        cursor.execute("TRUNCATE pemasukan, pengeluaran RESTART IDENTITY")
        conn.commit()

        if GOOGLE_READY:
            sheet_pm.clear()
            sheet_pg.clear()
            sheet_pm.append_row(["No Transaksi", "Nominal", "Tanggal"])
            sheet_pg.append_row(["No Transaksi", "Belanja", "Kategori", "Nominal", "Merchant", "Tanggal"])

        await update.message.reply_text("Data berhasil direset ✅")
        return

    # ================= CEK SALDO =================
    if text == "Cek Saldo":
        cursor.execute("SELECT COALESCE(SUM(jumlah),0) FROM pemasukan")
        pm = cursor.fetchone()[0]
        cursor.execute("SELECT COALESCE(SUM(jumlah),0) FROM pengeluaran")
        pg = cursor.fetchone()[0]
        await update.message.reply_text(
            f"Pemasukan: Rp {pm:,}\nPengeluaran: Rp {pg:,}\nSaldo: Rp {pm-pg:,}"
        )
        return

    # ================= PENGELUARAN TERBESAR =================
    if text == "Pengeluaran Terbesar":
        cursor.execute("SELECT keterangan,jumlah,merchant FROM pengeluaran ORDER BY jumlah DESC LIMIT 1")
        data = cursor.fetchone()
        if data:
            await update.message.reply_text(f"{data[0]}\nRp {data[1]:,}\nMerchant: {data[2]}")
        else:
            await update.message.reply_text("Belum ada data.")
        return

    # ================= PEMASUKAN =================
    if text == "Pemasukan":
        context.user_data["mode"] = "pm_jumlah"
        await update.message.reply_text("Masukkan nominal:")
        return

    if context.user_data.get("mode") == "pm_jumlah":
        jumlah = validasi_nominal(text)
        if not jumlah:
            await update.message.reply_text("Masukkan angka valid.")
            return
        context.user_data["jumlah"] = jumlah
        context.user_data["mode"] = "pm_tanggal"
        await update.message.reply_text("Tanggal (YYYY-MM-DD / hari ini / kemarin):")
        return

    if context.user_data.get("mode") == "pm_tanggal":
        tanggal = parse_tanggal(text)
        if not tanggal:
            await update.message.reply_text("Format tanggal salah.")
            return

        no = generate_no("pemasukan")
        cursor.execute(
            "INSERT INTO pemasukan (no_transaksi,jumlah,tanggal) VALUES (%s,%s,%s)",
            (no, context.user_data["jumlah"], tanggal)
        )
        conn.commit()

        if GOOGLE_READY:
            sheet_pm.append_row([no, context.user_data["jumlah"], tanggal])

        await update.message.reply_text(f"Disimpan ✅\nNo: {no}")
        context.user_data.clear()
        return

    # ================= PENGELUARAN =================
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
        await update.message.reply_text("Nominal?")
        return

    if context.user_data.get("mode") == "pg_jumlah":
        jumlah = validasi_nominal(text)
        if not jumlah:
            await update.message.reply_text("Masukkan angka valid.")
            return
        context.user_data["jumlah"] = jumlah
        context.user_data["mode"] = "pg_merchant"
        await update.message.reply_text("Merchant?")
        return

    if context.user_data.get("mode") == "pg_merchant":
        context.user_data["merchant"] = text
        context.user_data["mode"] = "pg_tanggal"
        await update.message.reply_text("Tanggal (YYYY-MM-DD / hari ini / kemarin):")
        return

    if context.user_data.get("mode") == "pg_tanggal":
        tanggal = parse_tanggal(text)
        if not tanggal:
            await update.message.reply_text("Format tanggal salah.")
            return

        no = generate_no("pengeluaran")

        cursor.execute("""
            INSERT INTO pengeluaran
            (no_transaksi,keterangan,kategori,jumlah,merchant,tanggal)
            VALUES (%s,%s,%s,%s,%s,%s)
        """,(no,
             context.user_data["keterangan"],
             context.user_data["kategori"],
             context.user_data["jumlah"],
             context.user_data["merchant"],
             tanggal))
        conn.commit()

        if GOOGLE_READY:
            sheet_pg.append_row([
                no,
                context.user_data["keterangan"],
                context.user_data["kategori"],
                context.user_data["jumlah"],
                context.user_data["merchant"],
                tanggal
            ])

        await update.message.reply_text(f"Disimpan ✅\nNo: {no}")
        context.user_data.clear()
        return

# ================= RUN =================
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))

print("Bot berjalan...")
app.run_polling(drop_pending_updates=True)

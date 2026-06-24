import os
import json
import gspread
from flask import Flask, jsonify
from supabase import create_client, Client

app = Flask(__name__)

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON")
SHEET_ID = os.environ.get("SHEET_ID") 

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route('/sync', methods=['POST'])
def sync_data():
    try:
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        gc = gspread.service_account_from_dict(creds_dict)
        sh = gc.open_by_key(SHEET_ID)
        ws = sh.worksheet("BALANCE_SHEET")
        data = ws.get_all_values()

        active_keys = set()
        to_insert = []
        
        # Row 4 is the first data row (index 3), Col 1 is the first data col (index 1)
        for row in data[4:]:
            for col in range(1, len(row), 10):
                if col + 5 >= len(row): continue
                
                room = str(data[2][col]).strip() # Room is in row 2
                date = str(row[col]).strip()[:10]
                client = str(row[col+1]).strip()
                bal_raw = str(row[col+5]).replace(',','').replace('Rs','').strip()
                remark = str(row[col+9])
                
                try:
                    balance = float(bal_raw)
                    if client and client.lower() != 'nan' and balance > 0:
                        key = f"{room}|{date}|{client}"
                        active_keys.add(key)
                        to_insert.append({
                            "room_number": room, "booking_date": date,
                            "client_name": client, "balance": balance, "remark": remark
                        })
                except: continue

        db_records = supabase.table('balance_payments').select('*').execute().data
        
        # Logic for DB sync...
        to_delete = [r['id'] for r in db_records if r.get('payment_status') != 'Paid' and f"{r['room_number']}|{str(r['booking_date'])[:10]}|{r['client_name']}" not in active_keys]
        
        if to_insert: supabase.table('balance_payments').upsert(to_insert).execute()
        if to_delete: supabase.table('balance_payments').delete().in_('id', to_delete).execute()

        return jsonify({"status": "success"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

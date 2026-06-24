import os
import json
import pandas as pd
import gspread
from flask import Flask, jsonify
from supabase import create_client, Client

app = Flask(__name__)

# Load Security Credentials
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
GOOGLE_CREDS_JSON = os.environ.get("GOOGLE_CREDS_JSON")
SHEET_ID = os.environ.get("SHEET_ID") 

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route('/sync', methods=['POST'])
def sync_data():
    try:
        # 1. Connect to Google Sheets
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        gc = gspread.service_account_from_dict(creds_dict)
        sh = gc.open_by_key(SHEET_ID)
        
        try:
            worksheet = sh.worksheet("BALANCE_SHEET")
        except:
            worksheet = sh.worksheet("Balance_Sheet")
            
        data = worksheet.get_all_values()
        df = pd.DataFrame(data)

        active_keys = set()
        to_insert = []
        
        # 2. Extract Data (Python effortlessly handles the horizontal layout)
        for row_idx in range(4, len(df)):
            for col_idx in range(1, len(df.columns), 10):
                try:
                    room = str(df.iloc[2, col_idx]).strip()
                    raw_date = df.iloc[row_idx, col_idx]
                    client = str(df.iloc[row_idx, col_idx+1]).strip()
                    raw_balance = df.iloc[row_idx, col_idx+5]
                    remark = str(df.iloc[row_idx, col_idx+9]) if pd.notna(df.iloc[row_idx, col_idx+9]) else ""

                    if pd.notna(client) and client != "" and client.lower() != "nan":
                        # Aggressive Math Cleaner
                        clean_bal_str = str(raw_balance).replace(',', '').replace('Rs', '').replace(' ', '')
                        try:
                            num_balance = float(clean_bal_str)
                            if num_balance > 0:
                                date_str = str(raw_date)[:10] if pd.notna(raw_date) else ""
                                key = f"{room}|{date_str}|{client}"
                                active_keys.add(key)
                                
                                to_insert.append({
                                    "room_number": room,
                                    "booking_date": date_str,
                                    "client_name": client,
                                    "balance": num_balance,
                                    "remark": remark
                                })
                        except ValueError:
                            pass
                except IndexError:
                    pass

        # 3. Smart Database Sync
        db_res = supabase.table('balance_payments').select('*').execute()
        db_records = db_res.data
        
        db_map = {}
        to_delete = []
        to_update = []
        
        for r in db_records:
            d_date = str(r.get('booking_date', ''))[:10]
            r_room = str(r.get('room_number', '')).strip()
            r_client = str(r.get('client_name', '')).strip()
            k = f"{r_room}|{d_date}|{r_client}"
            db_map[k] = r
            
            if r.get('payment_status') != 'Paid':
                if k not in active_keys:
                    to_delete.append(r['id'])

        final_inserts = []
        for item in to_insert:
            k = f"{item['room_number']}|{item['booking_date']}|{item['client_name']}"
            if k in db_map:
                db_record = db_map[k]
                if db_record.get('payment_status') != 'Paid':
                    if float(db_record.get('balance', 0)) != float(item['balance']):
                        to_update.append({"id": db_record['id'], "updates": item})
            else:
                final_inserts.append(item)

        # 4. Execute Changes Safely
        if final_inserts:
            supabase.table('balance_payments').upsert(final_inserts).execute()
        
        if to_delete:
            supabase.table('balance_payments').delete().in_('id', to_delete).execute()
            
        for u in to_update:
            supabase.table('balance_payments').update(u['updates']).eq('id', u['id']).execute()

        return jsonify({"status": "success"})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))

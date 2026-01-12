import streamlit as st
import json
import re
import pandas as pd
import requests
from bs4 import BeautifulSoup
from deep_translator import GoogleTranslator
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
import io

# --- Configuration ---
APP_PASSWORD = "Abcd@1234"
GRAPHQL_URL = "https://www.fresha.com/graphql"
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

def check_password():
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False
    if st.session_state["password_correct"]: return True
    st.title("🔒 Access Restricted")
    password_input = st.text_input("Enter App Password", type="password")
    if st.button("Unlock"):
        if password_input == APP_PASSWORD:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("🚫 Incorrect password")
    return False

def extract_ids(complex_str):
    """Extracts all s: and sv: IDs from the messy string."""
    if not complex_str: return []
    return re.findall(r'(s:\d+|sv:\d+)', str(complex_str))

def split_text(text):
    if not text: return "", ""
    text = str(text).strip()
    en, ar = "", ""
    if '|' in text:
        parts = [p.strip() for p in text.split('|')]
        for p in parts:
            if re.search(r'[\u0600-\u06FF]', p): ar = p
            else: en = p
    else:
        en_match = re.findall(r'[a-zA-Z0-9\s&\'\.]+', text)
        ar_match = re.findall(r'[\u0600-\u06FF\s]+', text)
        en = " ".join([m.strip() for m in en_match if m.strip()]).strip()
        ar = " ".join([m.strip() for m in ar_match if m.strip()]).strip()
    return en, ar

def process_translation(en_val, ar_val):
    t_en, t_ar = False, False
    if ar_val and not en_val:
        try:
            en_val = GoogleTranslator(source='ar', target='en').translate(ar_val)
            t_en = True
        except: pass
    elif en_val and not ar_val:
        try:
            ar_val = GoogleTranslator(source='en', target='ar').translate(en_val)
            t_ar = True
        except: pass
    return en_val, ar_val, t_en, t_ar

def fetch_staff_services(slug, emp_id):
    params = {
        "extensions": json.dumps({"persistedQuery": {"version": 1, "sha256Hash": "d099e71de92492ca928c6f7e5522aeea5328d4cda0b20e34a588558377f23390"}}),
        "variables": json.dumps({"employeeId": emp_id, "locationSlug": slug, "includeServices": True})
    }
    try:
        res = requests.get(GRAPHQL_URL, params=params, headers=HEADERS, timeout=10)
        return res.json().get('data', {}).get('employeeProfile', {}).get('categories', [])
    except:
        return []

def fetch_full_salon_data(salon_url):
    try:
        base_res = requests.get(salon_url, headers=HEADERS, timeout=10)
        soup = BeautifulSoup(base_res.text, 'html.parser')
        next_data_script = soup.find('script', id='__NEXT_DATA__')
        full_page_json = json.loads(next_data_script.string)
        build_id = full_page_json.get('buildId')
        match = re.search(r'/a/([^/?#]+)', salon_url)
        handle = match.group(1)
        json_url = f"https://www.fresha.com/_next/data/{build_id}/a/{handle}.json"
        service_json = requests.get(json_url, headers=HEADERS, timeout=10).json()
        return {"page_json": full_page_json, "service_json": service_json, "slug": handle}, None
    except Exception as e:
        return None, str(e)

if check_password():
    st.title("✂️ SALON DATA SCRAPER (FIXED)")
    url_input = st.text_input("Paste Fresha Salon Homepage URL:")
    
    if st.button("Fetch Salon & Team Data"):
        data, err = fetch_full_salon_data(url_input)
        if err: st.error(err)
        else:
            st.session_state["master_data"] = data
            st.success("✅ Main data fetched!")

    if "master_data" in st.session_state and st.session_state["master_data"]:
        master = st.session_state["master_data"]
        
        if st.button("🚀 Generate Final Excel"):
            # 1. Gather Team
            employee_data = master['page_json']['props']['pageProps'].get('location', {}).get('employeeProfiles', {}).get('edges', [])
            emp_ids = []
            team_rows = []
            for edge in employee_data:
                node = edge['node']
                emp_ids.append((node['employeeId'], node['displayName']))
                team_rows.append({
                    "Name": node['displayName'],
                    "Job Title": node.get('jobTitle'),
                    "Avatar URL": node.get('avatar', {}).get('url') if node.get('avatar') else ""
                })

            # 2. Build Multi-Layer Map
            id_to_staff = {}   # { ID: [Names] }
            name_to_staff = {} # { Name: [Names] }
            
            st.write("Extracting staff assignments...")
            prog = st.progress(0)
            for i, (eid, ename) in enumerate(emp_ids):
                prog.progress((i + 1) / len(emp_ids))
                categories = fetch_staff_services(master['slug'], eid)
                for cat in categories:
                    for item in cat.get('items', []):
                        # Map by ID
                        sid = item.get('id')
                        if sid:
                            id_to_staff.setdefault(sid, []).append(ename)
                        # Map by Name (Lowercase for fuzzy match)
                        sname = item.get('name', '').lower().strip()
                        name_to_staff.setdefault(sname, []).append(ename)

            # 3. Process Items
            items_list, highlights = [], []
            menu_data = master['service_json']['pageProps'].get('services') or master['service_json']['pageProps'].get('categories') or []
            
            for g in menu_data:
                g_name = g.get('name', '')
                for item in g.get('items', []):
                    # Try matching by ID first
                    found_staff = []
                    extracted_ids = extract_ids(item.get('id'))
                    for eid in extracted_ids:
                        if eid in id_to_staff:
                            found_staff.extend(id_to_staff[eid])
                    
                    # Fallback to Name match if ID failed
                    if not found_staff:
                        clean_name = item.get('name', '').lower().strip()
                        found_staff = name_to_staff.get(clean_name, [])
                    
                    # Unique names
                    found_staff = sorted(list(set(found_staff)))
                    
                    c_en, c_ar, ce_t, ca_t = process_translation(*split_text(g_name))
                    i_en, i_ar, ie_t, ia_t = process_translation(*split_text(item.get('name', '')))
                    d_en, d_ar, de_t, da_t = process_translation(*split_text(item.get('description') or ""))
                    
                    row_num = len(items_list) + 2
                    h = [idx+1 for idx, val in enumerate([ce_t, ca_t, ie_t, ia_t, de_t, da_t]) if val]
                    if h: highlights.append((row_num, h))

                    items_list.append({
                        "Category (EN)": c_en, "Category (AR)": c_ar,
                        "Service (EN)": i_en, "Service (AR)": i_ar,
                        "Desc (EN)": d_en, "Desc (AR)": d_ar,
                        "Price": item.get('formattedRetailPrice') or "",
                        "DURATION": item.get('caption', ''),
                        "QUALIFIED STAFF": ", ".join(found_staff)
                    })

            # 4. Save
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                pd.DataFrame(items_list).to_excel(writer, sheet_name='ITEMS', index=False)
                pd.DataFrame(team_rows).to_excel(writer, sheet_name='TEAM', index=False)
            
            output.seek(0)
            wb = load_workbook(output)
            ws = wb['ITEMS']
            yellow = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')
            for r_idx, cols in highlights:
                for c_idx in cols: ws.cell(row=r_idx, column=c_idx).fill = yellow
            
            final_out = io.BytesIO()
            wb.save(final_out)
            st.success("✅ Excel Ready!")
            st.download_button("📥 Download", final_out.getvalue(), "salon_data.xlsx")
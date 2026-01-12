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
    """Translates missing side and returns (en, ar, was_en_translated, was_ar_translated)"""
    translated_en = False
    translated_ar = False
    if ar_val and not en_val:
        try:
            en_val = GoogleTranslator(source='ar', target='en').translate(ar_val)
            translated_en = True
        except: pass
    elif en_val and not ar_val:
        try:
            ar_val = GoogleTranslator(source='en', target='ar').translate(en_val)
            translated_ar = True
        except: pass
    return en_val, ar_val, translated_en, translated_ar

def fetch_salon_json(salon_url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        match = re.search(r'/a/([^/?#]+)', salon_url)
        if not match: return None, "Invalid URL handle."
        handle = match.group(1)
        base_res = requests.get(salon_url, headers=headers, timeout=10)
        soup = BeautifulSoup(base_res.text, 'html.parser')
        next_data_script = soup.find('script', id='__NEXT_DATA__')
        build_id = json.loads(next_data_script.string).get('buildId')
        json_url = f"https://www.fresha.com/_next/data/{build_id}/a/{handle}.json"
        json_res = requests.get(json_url, headers=headers, timeout=10)
        return json_res.json(), None
    except Exception as e:
        return None, str(e)

def find_key_recursive(data, key_name):
    if isinstance(data, dict):
        if key_name in data: return data[key_name]
        for v in data.values():
            res = find_key_recursive(v, key_name)
            if res: return res
    elif isinstance(data, list):
        for i in data:
            res = find_key_recursive(i, key_name)
            if res: return res
    return None

if check_password():
    st.set_page_config(page_title="SALON JSON to EXCEL", page_icon="✂️")
    st.title("✂️ SALON JSON to EXCEL")

    if "raw_data" not in st.session_state:
        st.session_state["raw_data"] = None

    tab1, tab2 = st.tabs(["🔗 Scan URL", "📄 Paste JSON"])

    with tab1:
        url_input = st.text_input("Paste Fresha URL:")
        if st.button("Fetch Data"):
            data, err = fetch_salon_json(url_input)
            if err: st.error(err)
            else: 
                st.session_state["raw_data"] = data
                st.success("✅ Data Retrieved!")

    with tab2:
        json_text = st.text_area("Paste JSON content:", height=200)
        if st.button("Load JSON"):
            try: 
                st.session_state["raw_data"] = json.loads(json_text)
                st.success("✅ JSON Loaded!")
            except: st.error("Invalid JSON")

    if st.session_state["raw_data"]:
        data = st.session_state["raw_data"]
        
        # 1. INFO DATA EXTRACTION
        loc_info = find_key_recursive(data, 'location') or {}
        info_rows = [
            {"Field": "Name", "Value": loc_info.get('name')},
            {"Field": "Description", "Value": loc_info.get('description')},
            {"Field": "Contact Number", "Value": loc_info.get('contactNumber')},
            {"Field": "Cover Image", "Value": loc_info.get('coverImage', {}).get('url')}
        ]
        
        # 2. MENU DATA EXTRACTION
        menu_data = find_key_recursive(data, 'services') or find_key_recursive(data, 'categories')
        
        if menu_data:
            st.info(f"Salon: **{loc_info.get('name', 'Unknown')}** | Groups: {len(menu_data)}")
            
            if st.button("🚀 Generate Excel"):
                items_list, cell_highlights = [], []
                
                # Flatten items
                all_items = []
                for group in menu_data:
                    for item in group.get('items', []):
                        all_items.append((group.get('name', ''), item))
                
                prog = st.progress(0)
                for idx, (g_name, item) in enumerate(all_items):
                    prog.progress((idx + 1) / len(all_items))
                    
                    # Category
                    c_en, c_ar, c_en_t, c_ar_t = process_translation(*split_text(g_name))
                    # Item Name
                    i_en, i_ar, i_en_t, i_ar_t = process_translation(*split_text(item.get('name', '')))
                    # Item Desc (Strictly using description field)
                    d_en, d_ar, d_en_t, d_ar_t = process_translation(*split_text(item.get('description') or ""))
                    
                    price = item.get('formattedRetailPrice') or item.get('price', {}).get('formatted', '')
                    duration = item.get('caption', '')  # Caption used as Duration
                    
                    # Track which columns to highlight (1-based index)
                    row_num = len(items_list) + 2
                    highlights = []
                    if c_en_t: highlights.append(1)
                    if c_ar_t: highlights.append(2)
                    if i_en_t: highlights.append(3)
                    if i_ar_t: highlights.append(4)
                    if d_en_t: highlights.append(5)
                    if d_ar_t: highlights.append(6)
                    
                    if highlights:
                        cell_highlights.append((row_num, highlights))

                    items_list.append({
                        "Category (EN)": c_en, "Category (AR)": c_ar,
                        "Service (EN)": i_en, "Service (AR)": i_ar,
                        "Desc (EN)": d_en, "Desc (AR)": d_ar,
                        "Price": price,
                        "DURATION": duration
                    })

                # Write Excel
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    pd.DataFrame(info_rows).to_excel(writer, sheet_name='INFO', index=False)
                    pd.DataFrame(items_list).to_excel(writer, sheet_name='ITEMS', index=False)
                
                output.seek(0)
                wb = load_workbook(output)
                ws = wb['ITEMS']
                yellow = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')
                
                # Apply highlight to SPECIFIC cells only
                for r_idx, cols in cell_highlights:
                    for c_idx in cols:
                        ws.cell(row=r_idx, column=c_idx).fill = yellow
                
                final_out = io.BytesIO()
                wb.save(final_out)
                st.success("✅ Ready!")
                st.download_button("📥 Download Excel", final_out.getvalue(), f"{loc_info.get('name','salon')}.xlsx")
        else:
            st.error("No service menu found in JSON.")
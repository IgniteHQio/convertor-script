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
    enh, arh = False, False
    if ar_val and not en_val:
        try:
            en_val = GoogleTranslator(source='ar', target='en').translate(ar_val)
            enh = True
        except: pass
    elif en_val and not ar_val:
        try:
            ar_val = GoogleTranslator(source='en', target='ar').translate(en_val)
            arh = True
        except: pass
    return en_val, ar_val, enh, arh

def find_key_recursive(data, key_names):
    """Deep search for specific keys (list of names) in messy JSON structures."""
    if isinstance(data, dict):
        for kn in key_names:
            if kn in data: return data[kn]
        for v in data.values():
            res = find_key_recursive(v, key_names)
            if res: return res
    elif isinstance(data, list):
        for i in data:
            res = find_key_recursive(i, key_names)
            if res: return res
    return None

def fetch_salon_json(salon_url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    try:
        match = re.search(r'/a/([^/?#]+)', salon_url)
        if not match: return None, "Could not find salon handle in URL."
        handle = match.group(1)
        base_res = requests.get(salon_url, headers=headers, timeout=10)
        soup = BeautifulSoup(base_res.text, 'html.parser')
        next_data_script = soup.find('script', id='__NEXT_DATA__')
        if not next_data_script: return None, "Failed to find Build ID."
        build_id = json.loads(next_data_script.string).get('buildId')
        
        # Use handle.json as requested
        json_url = f"https://www.fresha.com/_next/data/{build_id}/a/{handle}.json"
        st.info(f"Fetching from: {json_url}")
        json_res = requests.get(json_url, headers=headers, timeout=10)
        return json_res.json(), None
    except Exception as e:
        return None, str(e)

# --- Main App ---

if check_password():
    st.set_page_config(page_title="SALON JSON to EXCEL", page_icon="✂️")
    st.title("✂️ SALON JSON to EXCEL")

    tab1, tab2, tab3 = st.tabs(["🔗 Scan via URL", "📄 Paste JSON Text", "📁 Upload JSON File"])
    raw_json_input = None

    with tab1:
        url_input = st.text_input("Paste Fresha Salon URL:")
        if st.button("Fetch & Process URL"):
            raw_json_input, err = fetch_salon_json(url_input)
            if err: st.error(err)

    with tab2:
        json_text = st.text_area("Paste JSON here:", height=200)
        if json_text:
            try: raw_json_input = json.loads(json_text)
            except: st.error("❌ Invalid JSON.")

    with tab3:
        uploaded_file = st.file_uploader("Upload JSON", type=["json"])
        if uploaded_file: raw_json_input = json.load(uploaded_file)

    if raw_json_input:
        # Search for categories OR services
        menu_data = find_key_recursive(raw_json_input, ['services', 'categories', 'screenServices'])
        location_info = find_key_recursive(raw_json_input, ['location'])
        salon_name = location_info.get('name', 'Salon_Export') if location_info else "Salon_Export"

        if menu_data and isinstance(menu_data, (list, dict)):
            # If we found screenServices, it's a dict containing categories
            if isinstance(menu_data, dict) and 'categories' in menu_data:
                menu_data = menu_data['categories']
            
            st.success(f"✅ Found {len(menu_data)} service groups for '{salon_name}'")
            
            if st.button("🚀 Generate Excel"):
                items_list, highlights = [], []
                for group in menu_data:
                    g_name = group.get('name', 'General')
                    c_en, c_ar, ceh, cah = process_translation(*split_text(g_name))
                    
                    for item in group.get('items', []):
                        i_name = item.get('name', '')
                        # Handle either 'description' or 'caption'
                        i_desc = item.get('description') or item.get('caption') or ""
                        
                        i_en, i_ar, ieh, iah = process_translation(*split_text(i_name))
                        id_en, id_ar, ideh, idah = process_translation(*split_text(i_desc))
                        
                        # Handle price objects
                        price_val = item.get('formattedRetailPrice') or item.get('price', {}).get('formatted', "")
                        
                        row_idx = len(items_list) + 2
                        if any([ceh, cah, ieh, iah, ideh, idah]):
                            highlights.append((row_idx, [1, 2, 3, 4, 5, 6]))

                        items_list.append({
                            "Category (EN)": c_en, "Category (AR)": c_ar,
                            "Service (EN)": i_en, "Service (AR)": i_ar,
                            "Desc (EN)": id_en, "Desc (AR)": id_ar,
                            "Price": price_val
                        })

                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    pd.DataFrame(items_list).to_excel(writer, sheet_name='ITEMS', index=False)
                output.seek(0)
                wb = load_workbook(output)
                ws = wb['ITEMS']
                yellow = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')
                for r, cs in highlights:
                    for c in cs: ws.cell(row=r, column=c).fill = yellow
                
                final_output = io.BytesIO()
                wb.save(final_output)
                st.download_button("📥 Download Excel", data=final_output.getvalue(), file_name=f"{salon_name}.xlsx")
        else:
            st.error("❌ Data structure unrecognized. Please paste the JSON manually in Tab 2 to verify.")
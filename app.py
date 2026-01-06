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

def find_menu_and_name(obj):
    """Recursively hunts for 'services' or 'categories' and salon name."""
    found_menu = None
    found_name = "Salon_Export"
    
    def walk(item):
        nonlocal found_menu, found_name
        if isinstance(item, dict):
            # Capture a likely salon name if not set
            if 'name' in item and found_name == "Salon_Export":
                if isinstance(item['name'], str) and 5 < len(item['name']) < 100:
                    found_name = item['name']
            
            # Check for keys that typically hold service lists
            for key in ['services', 'categories', 'screenServices']:
                if key in item and isinstance(item[key], list) and len(item[key]) > 0:
                    # Check if the list contains objects with an 'items' list inside
                    if isinstance(item[key][0], dict) and 'items' in item[key][0]:
                        found_menu = item[key]
                        return
            
            for v in item.values():
                if found_menu: return
                walk(v)
        elif isinstance(item, list):
            for i in item:
                if found_menu: return
                walk(i)

    walk(obj)
    return found_menu, found_name

# --- Main App ---
if check_password():
    st.set_page_config(page_title="SALON JSON to EXCEL", page_icon="✂️")
    st.title("✂️ SALON JSON to EXCEL")

    if "raw_data" not in st.session_state:
        st.session_state["raw_data"] = None

    tab1, tab2 = st.tabs(["🔗 Scan URL", "📄 Paste JSON"])

    with tab1:
        url_input = st.text_input("Paste Fresha URL:", key="url_box")
        if st.button("Fetch Data"):
            with st.spinner("Connecting to Fresha..."):
                data, err = fetch_salon_json(url_input)
                if err: st.error(f"Error: {err}")
                else: 
                    st.session_state["raw_data"] = data
                    st.success("✅ JSON data successfully retrieved!")

    with tab2:
        json_text = st.text_area("Paste JSON content:", height=200)
        if st.button("Load JSON"):
            try: 
                st.session_state["raw_data"] = json.loads(json_text)
                st.success("✅ JSON Loaded!")
            except: st.error("Invalid JSON format.")

    # --- Processing logic ---
    if st.session_state["raw_data"]:
        data = st.session_state["raw_data"]
        menu_data, salon_name = find_menu_and_name(data)

        if menu_data:
            st.info(f"📍 Salon: **{salon_name}** | Found **{len(menu_data)}** service groups.")
            
            if st.button("🚀 Start Translation & Generate Excel"):
                items_list, highlights = [], []
                
                # Flatten the list for the progress bar
                all_items = []
                for group in menu_data:
                    group_name = group.get('name', 'General')
                    for item in group.get('items', []):
                        all_items.append((group_name, item))
                
                total_items = len(all_items)
                progress_bar = st.progress(0)
                status_text = st.empty()

                for idx, (group_name, item) in enumerate(all_items):
                    # Update progress
                    progress_bar.progress((idx + 1) / total_items)
                    status_text.text(f"Processing {idx+1} of {total_items} items...")

                    # 1. Category
                    c_en, c_ar, ceh, cah = process_translation(*split_text(group_name))
                    
                    # 2. Item details
                    i_name = item.get('name', '')
                    i_desc = item.get('description') or item.get('caption') or ""
                    
                    # Handle multiple price formats found in different Fresha JSON versions
                    price = (item.get('formattedRetailPrice') or 
                             item.get('price', {}).get('formatted') or 
                             item.get('retailPrice', {}).get('value', ""))
                    
                    i_en, i_ar, ieh, iah = process_translation(*split_text(i_name))
                    id_en, id_ar, ideh, idah = process_translation(*split_text(i_desc))
                    
                    row_idx = len(items_list) + 2
                    if any([ceh, cah, ieh, iah, ideh, idah]):
                        highlights.append((row_idx, [1, 2, 3, 4, 5, 6]))

                    items_list.append({
                        "Category (EN)": c_en, "Category (AR)": c_ar,
                        "Service (EN)": i_en, "Service (AR)": i_ar,
                        "Desc (EN)": id_en, "Desc (AR)": id_ar,
                        "Price": price
                    })

                # Create Excel file in memory
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    pd.DataFrame(items_list).to_excel(writer, sheet_name='MENU', index=False)
                
                output.seek(0)
                wb = load_workbook(output)
                ws = wb['MENU']
                yellow = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')
                for r, cs in highlights:
                    for c in cs: ws.cell(row=r, column=c).fill = yellow
                
                final_output = io.BytesIO()
                wb.save(final_output)
                
                st.success("✨ Processing Complete!")
                st.download_button(
                    label="📥 Download Excel File", 
                    data=final_output.getvalue(), 
                    file_name=f"{salon_name.replace(' ', '_')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        else:
            st.error("❌ Structure not recognized. Could not find 'services' or 'categories' keys.")
            with st.expander("View Debug JSON"):
                st.json(data)

    if st.button("🧹 Reset App"):
        st.session_state["raw_data"] = None
        st.rerun()
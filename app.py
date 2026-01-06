import streamlit as st
import json
import re
import pandas as pd
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

# --- App Logic ---

if check_password():
    st.set_page_config(page_title="SALON JSON to EXCEL", page_icon="✂️")
    st.title("✂️ SALON JSON to EXCEL")

    json_text = st.text_area("Paste the Full JSON content here:", height=300)
    
    if json_text:
        try:
            data = json.loads(json_text)
            
            # --- Targeted Extraction for your specific JSON ---
            # Path: pageProps -> initialData -> bookingServices -> categories
            page_props = data.get('pageProps', {})
            init_data = page_props.get('initialData', {})
            
            # 1. Get Salon Name
            salon_name = "Salon_Export"
            # Try to find name in the location profile
            slug = page_props.get('locationSlug', '')
            loc_profile = init_data.get('bookingLocationProfile', {}).get(slug, {}).get('location', {})
            salon_name = loc_profile.get('name', 'Salon_Export')

            # 2. Get Categories
            categories = init_data.get('bookingServices', {}).get('categories', [])

            if not categories:
                st.warning("Could not find categories in the standard path. Trying Deep Search...")
                # Fallback: Deep Search if Fresha moves the keys
                def find_categories(obj):
                    if isinstance(obj, dict):
                        if 'categories' in obj and isinstance(obj['categories'], list):
                            return obj['categories']
                        for v in obj.values():
                            res = find_categories(v)
                            if res: return res
                    elif isinstance(obj, list):
                        for i in obj:
                            res = find_categories(i)
                            if res: return res
                    return None
                categories = find_categories(data)

            if categories:
                st.success(f"✅ Success! Found {len(categories)} categories for '{salon_name}'")
                
                if st.button("🚀 Generate Excel"):
                    with st.spinner("Translating missing text..."):
                        items_list, highlights = [], []
                        
                        for cat in categories:
                            cat_name = cat.get('name', '')
                            c_en, c_ar, ceh, cah = process_translation(*split_text(cat_name))
                            
                            for item in cat.get('items', []):
                                i_name = item.get('name', '')
                                i_desc = item.get('description', '')
                                i_en, i_ar, ieh, iah = process_translation(*split_text(i_name))
                                id_en, id_ar, ideh, idah = process_translation(*split_text(i_desc))
                                
                                row_idx = len(items_list) + 2
                                # Highlight if we had to translate something
                                if any([ceh, cah, ieh, iah, ideh, idah]):
                                    highlights.append((row_idx, [1, 2, 3, 4, 5, 6]))

                                items_list.append({
                                    "Category (EN)": c_en,
                                    "Category (AR)": c_ar,
                                    "Service Name (EN)": i_en,
                                    "Service Name (AR)": i_ar,
                                    "Description (EN)": id_en,
                                    "Description (AR)": id_ar,
                                    "Price": item.get('price', {}).get('formatted', '')
                                })

                        # Create Excel
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            pd.DataFrame(items_list).to_excel(writer, sheet_name='MENU', index=False)
                        
                        output.seek(0)
                        wb = load_workbook(output)
                        ws = wb['MENU']
                        yellow = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')
                        for r, cols in highlights:
                            for c in cols:
                                ws.cell(row=r, column=c).fill = yellow
                        
                        final_output = io.BytesIO()
                        wb.save(final_output)
                        st.download_button(
                            label="📥 Download Translated Excel",
                            data=final_output.getvalue(),
                            file_name=f"{salon_name.replace(' ', '_')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
            else:
                st.error("❌ Still could not find any service categories in this JSON. Please ensure you copied the FULL content of the JSON file.")

        except json.JSONDecodeError:
            st.error("❌ The text you pasted is not valid JSON. Please copy the entire file content.")
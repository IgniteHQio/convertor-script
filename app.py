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

# --- Helper Functions ---

def check_password():
    """Returns True if the user had the correct password."""
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if st.session_state["password_correct"]:
        return True

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

# --- Main App ---

if check_password():
    st.set_page_config(page_title="SALON JSON to EXCEL", page_icon="✂️")
    st.title("✂️ SALON JSON to EXCEL")
    st.markdown("Convert Fresha JSON data into translated, formatted Excel files.")

    tab1, tab2 = st.tabs(["📄 Paste JSON Text", "📁 Upload JSON File"])
    raw_json_input = None

    with tab1:
        json_text = st.text_area("Paste the JSON code here:", height=300, placeholder='{"data": {"bookingFlowInitialize": ...}}')
        if json_text:
            try:
                raw_json_input = json.loads(json_text)
                st.success("JSON Code Validated!")
            except json.JSONDecodeError:
                st.error("❌ Invalid JSON format. Please make sure you copied the full code.")

    with tab2:
        uploaded_file = st.file_uploader("Upload your fresha.json file", type=["json"])
        if uploaded_file:
            raw_json_input = json.load(uploaded_file)
            st.success("File Uploaded Successfully!")

    # --- Processing Logic ---

    if raw_json_input:
        # Standardize the data path
        booking_data = raw_json_input.get('data', {}).get('bookingFlowInitialize', raw_json_input)
        
        if 'layout' in booking_data:
            if st.button("🚀 Generate & Download Excel"):
                with st.spinner("Processing translations and creating file..."):
                    try:
                        cart = booking_data['layout']['cart']
                        full_name = cart.get('name', 'Salon')
                        
                        # Filename logic
                        name_en, _ = split_text(full_name)
                        clean_name = "".join(c for c in name_en if c.isalnum() or c.isspace()).strip()
                        excel_filename = f"{clean_name}.xlsx" if clean_name else "Salon_Export.xlsx"

                        # 1. INFO Sheet
                        df_info = pd.DataFrame([
                            {"Field": "Salon Name", "Value": full_name},
                            {"Field": "Address", "Value": cart.get('address')},
                            {"Field": "Avatar URL", "Value": cart.get('avatarUrl')}
                        ])

                        # 2. ITEMS Sheet
                        items_list, highlights = [], []
                        categories = booking_data['screenServices']['categories']

                        for cat in categories:
                            c_en, c_ar, ceh, cah = process_translation(*split_text(cat.get('name', '')))
                            cd_en, cd_ar, cdeh, cdah = process_translation(*split_text(cat.get('description', '')))
                            
                            for item in cat.get('items', []):
                                i_en, i_ar, ieh, iah = process_translation(*split_text(item.get('name', '')))
                                id_en, id_ar, ideh, idah = process_translation(*split_text(item.get('description', '')))
                                
                                row_idx = len(items_list) + 2
                                flags = [ceh, cah, cdeh, cdah, ieh, iah, ideh, idah]
                                cols = [idx + 1 for idx, flag in enumerate(flags) if flag]
                                if cols: highlights.append((row_idx, cols))

                                items_list.append({
                                    "Cat Name (EN)": c_en, "Cat Name (AR)": c_ar,
                                    "Cat Desc (EN)": cd_en, "Cat Desc (AR)": cd_ar,
                                    "Item Name (EN)": i_en, "Item Name (AR)": i_ar,
                                    "Item Desc (EN)": id_en, "Item Desc (AR)": id_ar,
                                    "Price": item.get('price', {}).get('formatted', '')
                                })

                        # Excel Memory Buffer
                        output = io.BytesIO()
                        with pd.ExcelWriter(output, engine='openpyxl') as writer:
                            df_info.to_excel(writer, sheet_name='INFO', index=False)
                            pd.DataFrame(items_list).to_excel(writer, sheet_name='ITEMS', index=False)
                        
                        output.seek(0)
                        wb = load_workbook(output)
                        ws = wb['ITEMS']
                        yellow = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')
                        for r, cs in highlights:
                            for c in cs: ws.cell(row=r, column=c).fill = yellow
                        
                        final_output = io.BytesIO()
                        wb.save(final_output)
                        
                        st.download_button(
                            label="📥 Download Excel File",
                            data=final_output.getvalue(),
                            file_name=excel_filename,
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                    except Exception as e:
                        st.error(f"Error: {e}")
        else:
            st.warning("⚠️ The JSON structure doesn't look like a Fresha menu. Please check the source.")
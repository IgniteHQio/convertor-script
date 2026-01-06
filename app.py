import streamlit as st
import json
import re
import pandas as pd
from deep_translator import GoogleTranslator
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
import io

# --- Logic Functions ---

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
        # Improved regex to extract English and Arabic blocks separately
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

# --- Streamlit Interface ---

st.set_page_config(page_title="Salon JSON Converter", page_icon="✂️")

st.title("Salon JSON to Excel Converter")
st.write("Upload your salon JSON file to extract information, auto-translate, and download as Excel.")

uploaded_file = st.file_uploader("Upload fresha.json", type="json")

if uploaded_file is not None:
    try:
        data = json.load(uploaded_file)
        st.success("JSON Loaded Successfully!")

        if st.button("Generate Excel File"):
            with st.spinner("Processing translations and formatting..."):
                # 1. Filename & Info
                cart = data['data']['bookingFlowInitialize']['layout']['cart']
                full_name = cart.get('name', '')
                name_en, _ = split_text(full_name)
                
                # Sanitize filename
                clean_name = "".join(c for c in name_en if c.isalnum() or c.isspace()).strip()
                excel_filename = f"{clean_name}.xlsx" if clean_name else "Salon_Export.xlsx"

                # INFO sheet rows
                info_rows = [
                    {"Field": "Salon Name", "Value": full_name},
                    {"Field": "Address", "Value": cart.get('address')},
                    {"Field": "Avatar URL", "Value": cart.get('avatarUrl')}
                ]
                df_info = pd.DataFrame(info_rows)

                # 2. Items Processing
                categories = data['data']['bookingFlowInitialize']['screenServices']['categories']
                items_data = []
                # Fixed variable name to 'highlights'
                highlights = []

                for cat in categories:
                    c_en_r, c_ar_r = split_text(cat.get('name', ''))
                    c_en, c_ar, ceh, cah = process_translation(c_en_r, c_ar_r)
                    
                    cd_en_r, cd_ar_r = split_text(cat.get('description', ''))
                    cd_en, cd_ar, cdeh, cdah = process_translation(cd_en_r, cd_ar_r)
                    
                    for item in cat.get('items', []):
                        i_en_r, i_ar_r = split_text(item.get('name', ''))
                        i_en, i_ar, ieh, iah = process_translation(i_en_r, i_ar_r)
                        
                        id_en_r, id_ar_r = split_text(item.get('description', ''))
                        id_en, id_ar, ideh, idah = process_translation(id_en_r, id_ar_r)
                        
                        row_idx = len(items_data) + 2 
                        # Flag list matches column order in items_data.append()
                        flags = [ceh, cah, cdeh, cdah, ieh, iah, ideh, idah]
                        cols = [idx + 1 for idx, flag in enumerate(flags) if flag]
                        
                        if cols: 
                            highlights.append((row_idx, cols))

                        items_data.append({
                            "Cat Name (EN)": c_en, "Cat Name (AR)": c_ar,
                            "Cat Desc (EN)": cd_en, "Cat Desc (AR)": cd_ar,
                            "Item Name (EN)": i_en, "Item Name (AR)": i_ar,
                            "Item Desc (EN)": id_en, "Item Desc (AR)": id_ar,
                            "Price": item.get('price', {}).get('formatted', '')
                        })

                # 3. Create Excel in Memory
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_info.to_excel(writer, sheet_name='INFO', index=False)
                    pd.DataFrame(items_data).to_excel(writer, sheet_name='ITEMS', index=False)
                
                # Apply Highlighting
                output.seek(0)
                wb = load_workbook(output)
                ws = wb['ITEMS']
                yellow_fill = PatternFill(start_color='FFFF00', end_color='FFFF00', fill_type='solid')
                
                for r, cs in highlights:
                    for c in cs: 
                        ws.cell(row=r, column=c).fill = yellow_fill
                
                # Final save to memory
                final_output = io.BytesIO()
                wb.save(final_output)
                
                st.download_button(
                    label="📥 Download Excel File",
                    data=final_output.getvalue(),
                    file_name=excel_filename,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                st.info(f"Generated filename: {excel_filename}")

    except Exception as e:
        st.error(f"Error processing file: {e}")
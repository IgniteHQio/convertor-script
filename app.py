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

# --- Helper Functions ---

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
        # Regex to extract English blocks and Arabic blocks
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

def fetch_fresha_data(url):
    """
    Fetches the Fresha page and extracts the GraphQL initial state JSON.
    """
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9'
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return None, f"Could not access page (Status {response.status_code})"
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Fresha embeds the GraphQL response in a script tag
        script_tag = soup.find('script', id='fresha-initial-state')
        if not script_tag:
            return None, "Unable to find salon data on this page. Make sure it's a valid Fresha salon link."

        raw_json = json.loads(script_tag.string)
        
        # Navigate the GraphQL state tree to find the booking data
        # Usually found in: data -> bookingFlowInitialize
        if 'data' in raw_json and 'bookingFlowInitialize' in raw_json['data']:
            return raw_json['data']['bookingFlowInitialize'], None
        
        return None, "The page loaded, but the salon menu data structure was not found."
    
    except Exception as e:
        return None, f"Error: {str(e)}"

# --- Streamlit UI ---

st.set_page_config(page_title="Fresha Menu Exporter", page_icon="📝")
st.title("Fresha Salon Exporter")
st.info("Paste a Fresha URL or upload a JSON file to generate a translated Excel menu.")

# User Input Options
tab1, tab2 = st.tabs(["Scan via URL", "Upload JSON"])
booking_data = None

with tab1:
    url_input = st.text_input("Enter Fresha Salon URL:", placeholder="https://www.fresha.com/a/...")
    if url_input:
        with st.spinner("Fetching data from Fresha..."):
            res_data, err = fetch_fresha_data(url_input)
            if err:
                st.error(err)
            else:
                booking_data = res_data
                st.success("Salon data retrieved successfully!")

with tab2:
    uploaded_file = st.file_uploader("Upload fresha.json", type="json")
    if uploaded_file:
        file_json = json.load(uploaded_file)
        # Handle cases where the uploaded JSON is the full raw response or just the inner data
        booking_data = file_json.get('data', {}).get('bookingFlowInitialize', file_json)

# --- Processing Logic ---

if booking_data and 'layout' in booking_data:
    if st.button("Generate & Download Excel"):
        with st.spinner("Translating and building Excel..."):
            try:
                cart = booking_data['layout']['cart']
                full_name = cart.get('name', 'Salon')
                
                # Filename logic
                name_en, _ = split_text(full_name)
                clean_name = "".join(c for c in name_en if c.isalnum() or c.isspace()).strip()
                excel_filename = f"{clean_name}.xlsx" if clean_name else "Salon_Menu.xlsx"

                # 1. INFO Sheet
                info_rows = [
                    {"Field": "Salon Name", "Value": full_name},
                    {"Field": "Address", "Value": cart.get('address')},
                    {"Field": "Avatar URL", "Value": cart.get('avatarUrl')}
                ]
                df_info = pd.DataFrame(info_rows)

                # 2. ITEMS Sheet
                categories = booking_data['screenServices']['categories']
                items_list = []
                highlights = []

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

                # Excel Creation
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
                st.error(f"Processing Error: {e}")
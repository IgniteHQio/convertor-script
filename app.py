import streamlit as st
import json
import re
import pandas as pd
import requests
from deep_translator import GoogleTranslator
from openpyxl import load_workbook
from openpyxl.styles import PatternFill
import io

# --- Logic Functions ---

def split_text(text):
    """Splits text into English and Arabic parts."""
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
    """Translates missing fields and flags for highlighting."""
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

def fetch_via_graphql(url):
    """Extracts slug and calls Fresha GraphQL using the CURL-provided hash."""
    # Extract location slug (the part after /a/)
    slug_match = re.search(r'/a/([^/?#]+)', url)
    if not slug_match:
        return None, "Invalid URL. Please ensure it is a Fresha salon link (contains /a/salon-name)."
    
    location_slug = slug_match.group(1)
    graphql_url = "https://www.fresha.com/graphql"

    payload = {
        "variables": {
            "input": {
                "locationSlug": location_slug,
                "capabilities": ["CART_ID", "SERVICE_ADDONS"]
            }
        },
        "extensions": {
            "persistedQuery": {
                "version": 1,
                "sha256Hash": "470f916eb8fb50235508f74481a13b68810ba805226c1546039b8ed6ee19c39d"
            }
        }
    }

    headers = {
        'Content-Type': 'application/json',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'x-client-platform': 'web'
    }

    try:
        response = requests.post(graphql_url, json=payload, headers=headers, timeout=20)
        res_data = response.json()
        
        if 'data' in res_data and 'bookingFlowInitialize' in res_data['data']:
            return res_data['data']['bookingFlowInitialize'], None
        elif 'errors' in res_data:
            return None, f"Fresha API Error: {res_data['errors'][0].get('message')}"
        return None, "Data structure not found in response."
    except Exception as e:
        return None, f"Request failed: {str(e)}"

# --- Streamlit UI ---

st.set_page_config(page_title="Fresha Salon Exporter", page_icon="📝")
st.title("Fresha Salon to Excel")
st.write("Automatically extract, translate, and highlight salon menus.")

tab1, tab2 = st.tabs(["Link Scraper", "JSON Upload"])
booking_data = None

with tab1:
    url_input = st.text_input("Paste Fresha URL:", placeholder="https://www.fresha.com/a/rosoleen-beauty-spa...")
    if url_input:
        with st.spinner("Fetching salon menu..."):
            res_data, err = fetch_via_graphql(url_input)
            if err: st.error(err)
            else:
                booking_data = res_data
                st.success("Salon data retrieved!")

with tab2:
    uploaded_file = st.file_uploader("Upload fresha.json", type="json")
    if uploaded_file:
        file_json = json.load(uploaded_file)
        booking_data = file_json.get('data', {}).get('bookingFlowInitialize', file_json)

# --- Common Processing ---

if booking_data and 'layout' in booking_data:
    if st.button("Generate & Download Excel"):
        with st.spinner("Translating missing values..."):
            try:
                cart = booking_data['layout']['cart']
                full_name = cart.get('name', 'Salon')
                name_en, _ = split_text(full_name)
                clean_name = "".join(c for c in name_en if c.isalnum() or c.isspace()).strip()
                excel_filename = f"{clean_name}.xlsx" if clean_name else "Salon_Export.xlsx"

                df_info = pd.DataFrame([
                    {"Field": "Salon Name", "Value": full_name},
                    {"Field": "Address", "Value": cart.get('address')},
                    {"Field": "Avatar URL", "Value": cart.get('avatarUrl')}
                ])

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
                st.download_button(label="📥 Download Excel", data=final_output.getvalue(), file_name=excel_filename)
                
            except Exception as e:
                st.error(f"Error: {e}")
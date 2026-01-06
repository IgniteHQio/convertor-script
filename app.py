import streamlit as st
import json
import re
import pandas as pd
import requests
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

def fetch_via_graphql(url):
    """
    Extracts Place ID from URL and performs a real GraphQL call to Fresha.
    """
    # 1. Extract pId from URL
    match = re.search(r'pId=(\d+)', url)
    if not match:
        return None, "Could not find Place ID (pId) in the URL. Please copy the full booking URL."
    
    place_id = match.group(1)
    graphql_url = "https://www.fresha.com/graphql"
    
    # 2. Mimic the Fresha GraphQL Request
    payload = {
        "operationName": "BookingFlowInitialize",
        "variables": {
            "input": {
                "placeId": place_id,
                "clientContext": {"source": "MARKETPLACE_DESKTOP"}
            }
        },
        "query": """
        query BookingFlowInitialize($input: BookingFlowInitializeInput!) {
          bookingFlowInitialize(input: $input) {
            layout { cart { name address avatarUrl } }
            screenServices {
              categories {
                name
                description
                items {
                  name
                  description
                  caption
                  price { formatted }
                }
              }
            }
          }
        }"""
    }

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Content-Type': 'application/json',
    }

    try:
        response = requests.post(graphql_url, json=payload, headers=headers)
        if response.status_code != 200:
            return None, f"GraphQL Request Failed: {response.status_code}"
        
        res_json = response.json()
        if 'data' in res_json and 'bookingFlowInitialize' in res_json['data']:
            return res_json['data']['bookingFlowInitialize'], None
        else:
            return None, "Invalid data returned from Fresha API."
    except Exception as e:
        return None, f"Network Error: {str(e)}"

# --- Streamlit UI ---

st.set_page_config(page_title="Fresha Direct Exporter", page_icon="📝")
st.title("Fresha Salon Exporter")

tab1, tab2 = st.tabs(["Scan via Booking URL", "Upload JSON"])
booking_data = None

with tab1:
    st.write("Paste the URL you see when clicking 'Book Now' or 'All Services'")
    url_input = st.text_input("Fresha Booking URL:", placeholder="https://www.fresha.com/a/.../booking?pId=12345")
    if url_input:
        with st.spinner("Calling Fresha GraphQL API..."):
            res_data, err = fetch_via_graphql(url_input)
            if err:
                st.error(err)
            else:
                booking_data = res_data
                st.success("Salon data fetched via GraphQL!")

with tab2:
    uploaded_file = st.file_uploader("Upload fresha.json", type="json")
    if uploaded_file:
        file_json = json.load(uploaded_file)
        # Unwrap data if it's a full raw response
        booking_data = file_json.get('data', {}).get('bookingFlowInitialize', file_json)

# --- Processing & Excel Download ---

if booking_data and 'layout' in booking_data:
    if st.button("Build & Download Excel"):
        with st.spinner("Translating and formatting..."):
            try:
                cart = booking_data['layout']['cart']
                full_name = cart.get('name', 'Salon')
                name_en, _ = split_text(full_name)
                
                clean_name = "".join(c for c in name_en if c.isalnum() or c.isspace()).strip()
                excel_filename = f"{clean_name}.xlsx" if clean_name else "Salon_Menu.xlsx"

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
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
    """Splits text into English and Arabic parts using regex blocks."""
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
    """Translates missing fields and returns highlight flags."""
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
    """Executes a GraphQL call using the Persisted Query hash from browser cURL."""
    # 1. Clean URL and extract slug
    clean_url = url.split('?')[0].rstrip('/')
    slug_match = re.search(r'/a/([^/]+)', clean_url)
    
    if not slug_match:
        return None, "Invalid URL. Make sure it contains '/a/salon-name'."
    
    location_slug = slug_match.group(1)
    # Remove /booking or /services from slug if present
    location_slug = re.sub(r'/(booking|all-offer|services)$', '', location_slug)
    
    graphql_url = "https://www.fresha.com/graphql"

    # Payload matching your cURL's persistedQuery hash
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

    # High-fidelity headers to mimic your browser cURL exactly
    headers = {
        'authority': 'www.fresha.com',
        'accept': '*/*',
        'content-type': 'application/json',
        'origin': 'https://www.fresha.com',
        'referer': f'https://www.fresha.com/a/{location_slug}',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'x-client-platform': 'web',
        'x-client-version': '2.8.829'
    }

    try:
        response = requests.post(graphql_url, json=payload, headers=headers, timeout=20)
        
        # If response is HTML, we are blocked by Cloudflare
        if "text/html" in response.headers.get("Content-Type", ""):
            return None, "Blocked by Fresha security. Please use the 'Upload JSON' tab."

        res_data = response.json()
        if 'data' in res_data and 'bookingFlowInitialize' in res_data['data']:
            return res_data['data']['bookingFlowInitialize'], None
        elif 'errors' in res_data:
            return None, f"API Error: {res_data['errors'][0].get('message')}"
        return None, "Data structure not found."
    except Exception as e:
        return None, f"Connection Error: {str(e)}"

# --- Streamlit UI ---

st.set_page_config(page_title="Fresha Salon Exporter", page_icon="📝", layout="centered")

st.title("✂️ Fresha Salon Exporter")
st.markdown("Convert Fresha salon menus into translated, formatted Excel files.")

# Sidebar Instructions
with st.sidebar:
    st.header("Manual JSON Guide")
    st.write("If the link scan is blocked by Fresha:")
    st.info("""
    1. Open Salon page in Chrome.
    2. Press **F12** (Inspect) -> **Network** tab.
    3. Type `graphql` in filter.
    4. Refresh page. 
    5. Right-click the `graphql` row -> **Save all as HAR** (or copy response).
    6. Upload that file in 'Upload JSON' tab.
    """)

tab1, tab2 = st.tabs(["🔗 Scan via URL", "📁 Upload JSON File"])
booking_data = None

with tab1:
    url_input = st.text_input("Paste Fresha Salon URL:", placeholder="https://www.fresha.com/a/rosoleen-beauty-spa...")
    if url_input:
        with st.spinner("Fetching salon menu via GraphQL..."):
            res_data, err = fetch_via_graphql(url_input)
            if err:
                st.error(err)
                st.warning("Tip: Use the 'Upload JSON' tab if this persists.")
            else:
                booking_data = res_data
                st.success("Salon data retrieved!")

with tab2:
    uploaded_file = st.file_uploader("Upload fresha.json (from Network tab)", type=["json", "har"])
    if uploaded_file:
        try:
            # Handle both raw JSON and HAR files
            content = json.load(uploaded_file)
            if 'log' in content: # It's a HAR file
                # Extract the first graphql response found in entries
                for entry in content['log']['entries']:
                    if 'graphql' in entry['request']['url']:
                        resp_text = entry['response']['content']['text']
                        content = json.loads(resp_text)
                        break
            
            booking_data = content.get('data', {}).get('bookingFlowInitialize', content)
            st.success("File loaded successfully!")
        except Exception as e:
            st.error(f"Error reading file: {e}")

# --- Common Processing ---

if booking_data and 'layout' in booking_data:
    if st.button("🚀 Generate & Download Excel"):
        with st.spinner("Translating and formatting..."):
            try:
                cart = booking_data['layout']['cart']
                full_name = cart.get('name', 'Salon')
                
                # Cleanup Filename
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

                # Excel Creation In-Memory
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
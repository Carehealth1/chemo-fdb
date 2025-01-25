import streamlit as st
import json
import pandas as pd
import requests
import urllib.parse
from datetime import datetime
import tempfile
import os
import PyPDF2
import anthropic
from typing import Dict, Any, List

# Configuration
st.set_page_config(
    page_title="Chemotherapy Order Template Analyzer",
    layout="wide",
    page_icon="💊"
)

# Initialize session state
if 'json_outputs' not in st.session_state:
    st.session_state['json_outputs'] = {}
if 'fdb_validation' not in st.session_state:
    st.session_state['fdb_validation'] = {}
if 'current_pdf_text' not in st.session_state:
    st.session_state['current_pdf_text'] = ""

# FDB API Configuration
FDB_BASE_URL = "https://api.fdbcloudconnector.com/CC/api/v1_4"

def make_fdb_request(endpoint: str, client_id: str, client_secret: str, params: dict = None) -> Dict[str, Any]:
    """Make an API request to FDB"""
    if params is None:
        params = {}
    
    params['callSystemName'] = 'ChemoAnalyzer'
    params['callid'] = datetime.now().strftime("%Y%m%d%H%M%S")
    
    headers = {
        "Authorization": f"SHAREDKEY {client_id}:{client_secret}",
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    try:
        url = f"{FDB_BASE_URL}/{endpoint}"
        if params:
            query_string = "&".join([f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items()])
            url = f"{url}{'&' if '?' in url else '?'}{query_string}"
        
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        return {
            "status": "success",
            "data": response.json(),
            "status_code": response.status_code
        }
    except requests.exceptions.RequestException as e:
        return {
            "status": "error",
            "message": str(e),
            "status_code": getattr(e.response, 'status_code', None)
        }

def process_pdf(file) -> str:
    """Extract text from PDF file"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
            tmp_file.write(file.getvalue())
            tmp_file_path = tmp_file.name

        text = ""
        with open(tmp_file_path, 'rb') as pdf_file:
            pdf_reader = PyPDF2.PdfReader(pdf_file)
            for page in pdf_reader.pages:
                text += page.extract_text() + "\n"
                
        os.unlink(tmp_file_path)
        return text
        
    except Exception as e:
        st.error(f"Error processing PDF: {str(e)}")
        return ""

def validate_regimen_with_fdb(regimen_data: Dict, client_id: str, client_secret: str) -> Dict[str, Any]:
    """Validate regimen medications using FDB API"""
    validation_results = {}
    
    if not regimen_data or 'phase1' not in regimen_data:
        return validation_results
    
    medications = regimen_data['phase1']['treatmentTemplate']['cycle']['medications']['day1']
    all_meds = (
        medications.get('pretreatmentMedications', []) +
        medications.get('chemotherapy', []) +
        medications.get('targetedTherapy', [])
    )
    
    for med in all_meds:
        med_name = med['name']
        
        # Search for drug in FDB
        search_params = {
            "searchtext": med_name,
            "searchtype": "contains",
            "limit": "1"
        }
        
        result = make_fdb_request(
            "PrescribableDrugs",
            client_id,
            client_secret,
            search_params
        )
        
        if result["status"] == "success" and "data" in result:
            drug_data = result["data"]
            if "Items" in drug_data and len(drug_data["Items"]) > 0:
                drug_id = drug_data["Items"][0]["PrescribableDrugID"]
                
                # Get drug interactions
                interactions = make_fdb_request(
                    f"PrescribableDrugs/{drug_id}/Interactions",
                    client_id,
                    client_secret
                )
                
                # Get dosing information
                dosing = make_fdb_request(
                    f"PrescribableDrugs/{drug_id}/DoseRecords",
                    client_id,
                    client_secret
                )
                
                validation_results[med_name] = {
                    "drug_info": drug_data["Items"][0],
                    "interactions": interactions.get("data", {}),
                    "dosing": dosing.get("data", {})
                }
    
    return validation_results

def display_validation_results(validation_results: Dict[str, Any]):
    """Display FDB validation results in a structured format"""
    if not validation_results:
        st.warning("No validation results available")
        return
    
    for med_name, results in validation_results.items():
        with st.expander(f"Validation Results: {med_name}"):
            col1, col2 = st.columns(2)
            
            with col1:
                st.subheader("Drug Information")
                if "drug_info" in results:
                    drug_info = results["drug_info"]
                    st.write(f"Generic: {drug_info.get('DispensableGenericDesc', 'N/A')}")
                    st.write(f"Route: {drug_info.get('RouteDesc', 'N/A')}")
                    st.write(f"Form: {drug_info.get('DoseFormDesc', 'N/A')}")
            
            with col2:
                st.subheader("Interactions")
                if "interactions" in results:
                    interactions = results["interactions"]
                    if isinstance(interactions, list):
                        for interaction in interactions:
                            st.warning(interaction)
                    else:
                        st.info("No significant interactions found")
            
            st.subheader("Dosing Information")
            if "dosing" in results:
                dosing = results["dosing"]
                if isinstance(dosing, dict) and "DoseRecords" in dosing:
                    for dose_record in dosing["DoseRecords"]:
                        st.write(f"- {dose_record.get('DoseDescription', 'N/A')}")

def main():
    st.title("Chemotherapy Order Template Analyzer")
    
    # Sidebar configuration
    with st.sidebar:
        st.header("Configuration")
        
        # FDB Credentials
        st.subheader("FDB API Credentials")
        fdb_client_id = st.text_input("FDB Client ID", type="password")
        fdb_client_secret = st.text_input("FDB Client Secret", type="password")
        
        # Anthropic API key for template processing
        st.subheader("Anthropic API Key")
        anthropic_api_key = st.text_input("API Key", type="password")
        
        st.markdown("---")
        
        # Upload section
        st.header("Upload Templates")
        uploaded_files = st.file_uploader(
            "Upload NCCN Template PDFs",
            accept_multiple_files=True,
            type=['pdf']
        )
    
    # Main content area
    tabs = st.tabs(["Template Analysis", "FDB Validation", "Treatment Calendar"])
    
    with tabs[0]:
        st.header("Template Analysis")
        
        if uploaded_files:
            for uploaded_file in uploaded_files:
                if uploaded_file.name not in st.session_state['json_outputs']:
                    with st.spinner(f"Processing {uploaded_file.name}..."):
                        # Extract text from PDF
                        pdf_text = process_pdf(uploaded_file)
                        
                        if pdf_text:
                            # Process with Claude
                            client = anthropic.Client(api_key=anthropic_api_key)
                            response = client.messages.create(
                                model="claude-3-opus-20240229",
                                max_tokens=4096,
                                temperature=0,
                                messages=[
                                    {
                                        "role": "user",
                                        "content": f"Extract structured regimen data from this template:\n\n{pdf_text}"
                                    }
                                ]
                            )
                            
                            try:
                                extracted_data = json.loads(response.content[0].text)
                                st.session_state['json_outputs'][uploaded_file.name] = extracted_data
                                
                                # Validate with FDB if credentials provided
                                if fdb_client_id and fdb_client_secret:
                                    validation_results = validate_regimen_with_fdb(
                                        extracted_data,
                                        fdb_client_id,
                                        fdb_client_secret
                                    )
                                    st.session_state['fdb_validation'][uploaded_file.name] = validation_results
                            
                            except json.JSONDecodeError:
                                st.error(f"Failed to parse JSON for {uploaded_file.name}")
                                st.code(response.content[0].text)
            
            # Display processed templates
            for filename, data in st.session_state['json_outputs'].items():
                with st.expander(f"Template: {filename}"):
                    st.json(data)
    
    with tabs[1]:
        st.header("FDB Validation")
        
        if not (fdb_client_id and fdb_client_secret):
            st.warning("Please provide FDB API credentials in the sidebar")
        elif 'fdb_validation' in st.session_state:
            for filename, validation_data in st.session_state['fdb_validation'].items():
                with st.expander(f"Validation Results: {filename}"):
                    display_validation_results(validation_data)
    
    with tabs[2]:
        st.header("Treatment Calendar")
        
        if st.session_state['json_outputs']:
            selected_template = st.selectbox(
                "Select Template",
                list(st.session_state['json_outputs'].keys())
            )
            
            if selected_template:
                regimen_data = st.session_state['json_outputs'][selected_template]
                
                # Create calendar view
                if 'phase1' in regimen_data:
                    cycle_data = regimen_data['phase1']['treatmentTemplate']['cycle']
                    cycle_length = int(cycle_data.get('duration', {}).get('numberOfDays', 28))
                    
                    # Create calendar grid
                    cols = st.columns(7)
                    for day in range(1, cycle_length + 1):
                        with cols[day % 7]:
                            with st.container():
                                st.markdown(f"**Day {day}**")
                                
                                # Display medications for this day
                                if day == 1:  # Assuming day 1 medications for now
                                    medications = cycle_data['medications']['day1']
                                    for med_type in ['chemotherapy', 'targetedTherapy']:
                                        if med_type in medications:
                                            for med in medications[med_type]:
                                                st.markdown(f"- {med['name']}: {med['dose']}")

if __name__ == "__main__":
    main()
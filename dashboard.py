import streamlit as st

st.set_page_config(
    page_title="AI Trading Platform",
    layout="wide"
)

st.title("AI Trading Platform")

st.write("""
Welcome to your trading research platform.

Use the sidebar to navigate between:

- Live Scanner
- Backtesting
- Trade History
- Settings
""")

st.subheader("Platform Status")

st.success("Core engine online")
st.success("Scanner available")
st.success("Risk engine available")
st.success("Portfolio manager available")
st.success("Dashboard running")

import streamlit as st
import pandas as pd
import altair as alt
from pathlib import Path
import calendar
import datetime

# Config
INPUT_FILE = Path("hourly_german_residual_load_and_prices_2024_present.csv")

st.set_page_config(page_title="Energy Charts Dashboard", layout="wide")

@st.cache_data
def load_data():
    if not INPUT_FILE.exists():
        return None
    df = pd.read_csv(INPUT_FILE)
    df['datetime'] = pd.to_datetime(df['datetime_utc'])
    df['year'] = df['datetime'].dt.year
    df['month'] = df['datetime'].dt.month
    df['date'] = df['datetime'].dt.date
    return df

def calculate_monthly_stats(df):
    # Reusing logic from monthly_stats.py
    
    def daily_spread(g):
        sorted_prices = g['day_ahead_price_eur_mwh'].sort_values()
        if len(sorted_prices) < 8: return None
        return sorted_prices.iloc[-4:].mean() - sorted_prices.iloc[:4].mean()

    # Daily Spreads
    daily_spreads = df.groupby(['year', 'month', 'date']).apply(lambda x: daily_spread(x)).reset_index(name='spread')
    monthly_spread = daily_spreads.groupby(['year', 'month'])['spread'].mean().reset_index(name='avg_spread')
    
    # Monthly Aggregates
    def monthly_agg(g):
        avg_price = g['day_ahead_price_eur_mwh'].mean()
        neg_hours = (g['day_ahead_price_eur_mwh'] < 0).sum()
        res_neg_price = g[g['residual_load_mw_avg'] < 0]['day_ahead_price_eur_mwh'].mean()
        res_high_price = g[g['residual_load_mw_avg'] > 60000]['day_ahead_price_eur_mwh'].mean()
        return pd.Series({
            'avg_price': avg_price,
            'neg_hours': neg_hours,
            'avg_price_res_neg': res_neg_price,
            'avg_price_res_high': res_high_price
        })

    monthly_stats = df.groupby(['year', 'month']).apply(monthly_agg).reset_index()
    merged = pd.merge(monthly_stats, monthly_spread, on=['year', 'month'])
    return merged

def calculate_capture_prices(df):
    # Reusing logic from solar_capture_prices.py
    df = df.copy()
    df['solar_revenue'] = df['solar_mw_avg'] * df['day_ahead_price_eur_mwh']
    
    # Positive Price Logic
    df_pos = df[df['day_ahead_price_eur_mwh'] >= 0].copy()
    
    monthly_grouped = df.groupby(['year', 'month']).agg({
        'solar_mw_avg': 'sum',
        'solar_revenue': 'sum',
        'day_ahead_price_eur_mwh': 'mean'
    }).reset_index()
    
    monthly_pos = df_pos.groupby(['year', 'month']).agg({
        'solar_mw_avg': 'sum',
        'solar_revenue': 'sum'
    }).reset_index().rename(columns={'solar_mw_avg': 'solar_mw_pos', 'solar_revenue': 'solar_rev_pos'})
    
    merged = pd.merge(monthly_grouped, monthly_pos, on=['year', 'month'], how='left')
    
    merged['pv_price'] = merged['solar_revenue'] / merged['solar_mw_avg']
    merged['pv_price_pos'] = merged['solar_rev_pos'] / merged['solar_mw_pos']
    merged['baseload_price'] = merged['day_ahead_price_eur_mwh']
    merged['capture_rate'] = merged['pv_price'] / merged['baseload_price']
    
    return merged

def main():
    st.title("🇩🇪 Energy Charts Dashboard")
    st.markdown("Analysis of German residual load, electricity prices, and solar capture rates.")

    df = load_data()
    if df is None:
        st.error(f"Data file `{INPUT_FILE}` not found. Please run the fetch script.")
        return

    tab1, tab2, tab3 = st.tabs(["Monthly Statistics", "Solar Capture Prices", "Scatter Plots"])

    with tab1:
        st.header("Monthly Market Statistics")
        stats_df = calculate_monthly_stats(df)
        
        # Interactive formatting
        years = sorted(stats_df['year'].unique())
        selected_years = st.multiselect("Select Years", years, default=years)
        
        show_df = stats_df[stats_df['year'].isin(selected_years)].copy()
        show_df['month_name'] = show_df['month'].apply(lambda x: calendar.month_abbr[x])
        
        # Pivot for better view? Or just show as list
        # Creating a similar pivot view as the PDF
        cols_to_show = ['month_name', 'year', 'avg_price', 'avg_spread', 'neg_hours', 'avg_price_res_neg', 'avg_price_res_high']
        st.dataframe(show_df[cols_to_show].style.format({
            'avg_price': "{:.2f} €",
            'avg_spread': "{:.2f} €",
            'neg_hours': "{:.0f}",
            'avg_price_res_neg': "{:.2f} €",
            'avg_price_res_high': "{:.2f} €"
        }), use_container_width=True)

    with tab2:
        st.header("Solar Capture Prices & Curtailment")
        cap_df = calculate_capture_prices(df)
        
        # Yearly Summary
        st.subheader("Yearly Overview")
        yearly_df = df.copy()
        yearly_df['solar_revenue'] = yearly_df['solar_mw_avg'] * yearly_df['day_ahead_price_eur_mwh']
        yearly_pos = yearly_df[yearly_df['day_ahead_price_eur_mwh'] >= 0]
        
        y_grp = yearly_df.groupby('year').agg({
            'solar_mw_avg': 'sum', 
            'solar_revenue': 'sum',
            'day_ahead_price_eur_mwh': 'mean'
        })
        y_pos_grp = yearly_pos.groupby('year').agg({'solar_mw_avg': 'sum', 'solar_revenue': 'sum'})
        
        y_res = pd.DataFrame({
            'PV Price': y_grp['solar_revenue'] / y_grp['solar_mw_avg'],
            'PV Price (Pos)': y_pos_grp['solar_revenue'] / y_pos_grp['solar_mw_avg'],
            'Baseload Price': y_grp['day_ahead_price_eur_mwh'],
        })
        y_res['Capture Rate'] = y_res['PV Price'] / y_res['Baseload Price']
        
        st.dataframe(y_res.style.format({
            'PV Price': "{:.2f} €",
            'PV Price (Pos)': "{:.2f} €",
            'Baseload Price': "{:.2f} €",
            'Capture Rate': "{:.1%}"
        }))

        st.subheader("Monthly Details")
        st.dataframe(cap_df[['year', 'month', 'pv_price', 'pv_price_pos', 'baseload_price', 'capture_rate']].style.format({
            'pv_price': "{:.2f} €",
            'pv_price_pos': "{:.2f} €",
            'baseload_price': "{:.2f} €",
            'capture_rate': "{:.1%}"
        }), use_container_width=True)

    with tab3:
        st.header("Residual Load vs. Price")
        
        years = sorted(df['year'].unique())
        c1, c2 = st.columns(2)
        sel_year = c1.selectbox("Year", years, index=len(years)-1) # Default last year
        sel_month = c2.selectbox("Month", list(calendar.month_name)[1:])
        
        month_idx = list(calendar.month_name).index(sel_month)
        
        chart_data = df[(df['year'] == sel_year) & (df['month'] == month_idx)]
        
        if chart_data.empty:
            st.warning("No data for selection.")
        else:
            chart = alt.Chart(chart_data).mark_circle(size=60).encode(
                x=alt.X('residual_load_mw_avg', title='Residual Load (MW)'),
                y=alt.Y('day_ahead_price_eur_mwh', title='Price (€/MWh)'),
                color=alt.value('steelblue'),
                tooltip=['datetime', 'residual_load_mw_avg', 'day_ahead_price_eur_mwh', 'solar_mw_avg']
            ).properties(height=600).interactive()
            
            st.altair_chart(chart, use_container_width=True)
            
        st.divider()
        st.subheader("Compare Months")
        # Comparison logic
        col1, col2 = st.columns(2)
        with col1:
            y1 = st.selectbox("Year A", years, index=0, key="y1")
            m1 = st.selectbox("Month A", list(calendar.month_name)[1:], index=0, key="m1")
        with col2:
            y2 = st.selectbox("Year B", years, index=len(years)-1, key="y2")
            m2 = st.selectbox("Month B", list(calendar.month_name)[1:], index=0, key="m2")
            
        d1 = df[(df['year'] == y1) & (df['month'] == list(calendar.month_name).index(m1))].copy()
        d1['Label'] = f"{m1} {y1}"
        d2 = df[(df['year'] == y2) & (df['month'] == list(calendar.month_name).index(m2))].copy()
        d2['Label'] = f"{m2} {y2}"
        
        comp_data = pd.concat([d1, d2])
        
        if not comp_data.empty:
            comp_chart = alt.Chart(comp_data).mark_circle(size=60).encode(
                x=alt.X('residual_load_mw_avg', title='Residual Load (MW)'),
                y=alt.Y('day_ahead_price_eur_mwh', title='Price (€/MWh)'),
                color='Label',
                tooltip=['datetime', 'residual_load_mw_avg', 'day_ahead_price_eur_mwh']
            ).properties(height=600).interactive()
            st.altair_chart(comp_chart, use_container_width=True)

if __name__ == "__main__":
    main()

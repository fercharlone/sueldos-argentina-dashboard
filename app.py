
# -*- coding: utf-8 -*-
import io
import requests
import pandas as pd
import numpy as np
import altair as alt
import streamlit as st
from dateutil.relativedelta import relativedelta

st.set_page_config(page_title="Sueldos ARS reales vs USD reales", layout="wide")

def to_month_start(s):
    s = pd.to_datetime(s, errors="coerce")
    return s.dt.to_period("M").dt.to_timestamp()

@st.cache_data(ttl=86400)
def fetch_cpi_us():
    url = "https://fred.stlouisfed.org/series/CPIAUCSL/downloaddata/CPIAUCSL.csv"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.rename(columns={"DATE":"fecha","CPIAUCSL":"cpi_us"}, inplace=True)
    df["fecha"] = to_month_start(df["fecha"])
    df = df[["fecha","cpi_us"]].dropna()
    return df

@st.cache_data(ttl=86400)
def read_csv_uploaded(file):
    df = pd.read_csv(file)
    return df

@st.cache_data(ttl=3600)
def read_csv_url(url):
    df = pd.read_csv(url)
    return df

def merge_all(sueldos_df, cpi_us_df):
    df = sueldos_df.copy()
    if "fecha" not in df.columns or "sueldo_nominal_ars" not in df.columns:
        st.error("El archivo/hoja debe tener al menos las columnas: fecha, sueldo_nominal_ars")
        st.stop()
    df["fecha"] = to_month_start(df["fecha"])
    keep = ["fecha","sueldo_nominal_ars"] + [c for c in ["usd_ars","cpi_ar","cpi_us"] if c in df.columns]
    df = df[keep].sort_values("fecha")
    if "cpi_us" not in df.columns:
        df = df.merge(cpi_us_df, on="fecha", how="left")
    return df

def compute_last_common_month(df):
    fechas = {}
    if "cpi_ar" in df.columns and df["cpi_ar"].notna().any():
        fechas["ars_real"] = df.dropna(subset=["sueldo_nominal_ars","cpi_ar"])["fecha"].max()
    if ("usd_ars" in df.columns and df["usd_ars"].notna().any() and
        "cpi_us" in df.columns and df["cpi_us"].notna().any()):
        fechas["usd_real"] = df.dropna(subset=["sueldo_nominal_ars","usd_ars","cpi_us"])["fecha"].max()
    last_common = min(fechas.values()) if fechas else df["fecha"].max()
    first = df["fecha"].min()
    return first, last_common, fechas

def deflate(series, cpi, cpi_base):
    return series * (cpi_base / cpi)

st.sidebar.title("Origen de datos")
mode = st.sidebar.radio(
    "Elegí una opción",
    options=["Subir CSV", "URL de Google Sheet (CSV)"],
    index=0
)
st.sidebar.caption("Columnas mínimas: fecha (YYYY-MM) y sueldo_nominal_ars. Opcionales: usd_ars (ARS/USD), cpi_ar (IPC AR), cpi_us (IPC US).")

input_df = None
if mode == "Subir CSV":
    up = st.sidebar.file_uploader("Subí el CSV", type=["csv"])
    if up is not None:
        input_df = read_csv_uploaded(up)
else:
    url = st.sidebar.text_input("Pega el enlace CSV de tu Google Sheet", help="En Google Sheets: Archivo → Compartir → Público con enlace. Luego usa la URL con '/export?format=csv'")
    if url:
        try:
            input_df = read_csv_url(url)
        except Exception as e:
            st.sidebar.error(f"No se pudo leer la URL. Detalle: {e}")

st.title("Sueldos: ARS reales vs USD reales (ajustados por inflación)")
st.caption("Seleccioná período, base y listo. La app detecta el último mes común entre las series.")

with st.expander("Ver cómo preparar el CSV / Google Sheet", expanded=False):
    st.markdown("""
**Estructura de columnas (encabezados exactos):**
- `fecha` → mes `YYYY-MM` (o fecha; se toma el primer día).
- `sueldo_nominal_ars` → sueldo nominal en pesos.
- `usd_ars` *(opcional)* → tipo de cambio ARS/USD (promedio mensual).
- `cpi_ar` *(opcional)* → IPC Argentina (nivel índice).
- `cpi_us` *(opcional)* → IPC de EE. UU. (nivel índice). Si falta, la app lo descarga de FRED.

> Para **ARS real** se requiere `cpi_ar`.
> Para **USD real** se requieren `usd_ars` y `cpi_us`.
""")

if input_df is None:
    st.info("Subí un CSV o pega la URL de Google Sheet. También podés probar con 'demo_sueldos.csv'.")
    st.stop()

cpi_us_df = pd.DataFrame(columns=["fecha","cpi_us"])
try:
    cpi_us_df = fetch_cpi_us()
except Exception as e:
    st.warning("No se pudo descargar CPI de EE. UU. (FRED). Si no cargás cpi_us, no se calculará USD real.")

df = merge_all(input_df, cpi_us_df).sort_values("fecha")
first, last_common, por_linea = compute_last_common_month(df)

st.sidebar.markdown("---")
st.sidebar.subheader("Período del gráfico")
start_default = first.to_pydatetime()
end_default = last_common.to_pydatetime()
date_range = st.sidebar.date_input("Rango (desde / hasta)", value=(start_default, end_default))
if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
    start_date, end_date = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
else:
    start_date, end_date = start_default, end_default

mask = (df["fecha"] >= start_date) & (df["fecha"] <= end_date)
df_r = df.loc[mask].copy()
if df_r.empty:
    st.error("No hay datos en el rango seleccionado.")
    st.stop()

st.sidebar.markdown("---")
st.sidebar.subheader("Base de precios")
base_choice = st.sidebar.radio("Elegí base", ["Último mes del rango", "Elegir mes específico"], index=0)
if base_choice == "Último mes del rango":
    base_month = df_r["fecha"].max()
else:
    base_month = pd.to_datetime(st.sidebar.date_input("Mes base", value=df_r["fecha"].max()))

cpi_ar_base = None
cpi_us_base = None
if "cpi_ar" in df_r.columns and df_r["cpi_ar"].notna().any():
    tmp = df_r.loc[df_r["fecha"] <= base_month, "cpi_ar"].dropna()
    if not tmp.empty: cpi_ar_base = tmp.iloc[-1]
if "cpi_us" in df_r.columns and df_r["cpi_us"].notna().any():
    tmp = df_r.loc[df_r["fecha"] <= base_month, "cpi_us"].dropna()
    if not tmp.empty: cpi_us_base = tmp.iloc[-1]

out = df_r[["fecha","sueldo_nominal_ars"]].copy()
out["ars_real"] = np.nan
out["usd_nominal"] = np.nan
out["usd_real"] = np.nan

if cpi_ar_base is not None:
    out["ars_real"] = out["sueldo_nominal_ars"] * (cpi_ar_base / df_r["cpi_ar"])

if "usd_ars" in df_r.columns and df_r["usd_ars"].notna().any():
    out["usd_nominal"] = out["sueldo_nominal_ars"] / df_r["usd_ars"]
    if cpi_us_base is not None:
        out["usd_real"] = out["usd_nominal"] * (cpi_us_base / df_r["cpi_us"])

series, labels = [], []
if out["ars_real"].notna().any(): series.append("ars_real"); labels.append("ARS real")
if out["usd_real"].notna().any(): series.append("usd_real"); labels.append("USD real (ajustado por inflación)")

st.write(f"**Último mes común detectado:** {last_common.strftime('%Y-%m')}")

if not series:
    st.error("Faltan series para graficar. Necesitás: cpi_ar para ARS real y/o usd_ars + cpi_us para USD real.")
    st.stop()

plot = out.melt(id_vars="fecha", value_vars=series, var_name="serie", value_name="valor")
plot["serie"] = plot["serie"].map(dict(zip(series, labels)))

chart = alt.Chart(plot).mark_line(interpolate="monotone").encode(
    x=alt.X("fecha:T", title="Fecha"),
    y=alt.Y("valor:Q", title="Monto"),
    color=alt.Color("serie:N", title="Serie"),
    tooltip=[alt.Tooltip("fecha:T","Fecha"), alt.Tooltip("serie:N","Serie"), alt.Tooltip("valor:Q","Valor", format=",.2f")]
).properties(height=460)
st.altair_chart(chart, use_container_width=True)

st.markdown("### Resumen de series")
def stats(s):
    s = s.dropna()
    return None if s.empty else dict(promedio=float(s.mean()), max=float(s.max()), min=float(s.min()), ultimo=float(s.iloc[-1]))

rows = []
if "ars_real" in series:
    r = stats(out["ars_real"]); 
    if r: rows.append({"Serie":"ARS real", **r})
if "usd_real" in series:
    r = stats(out["usd_real"]);
    if r: rows.append({"Serie":"USD real (ajustado)", **r})
if rows:
    st.dataframe(pd.DataFrame(rows).style.format({"promedio":"{:,.2f}","max":"{:,.2f}","min":"{:,.2f}","ultimo":"{:,.2f}"}), use_container_width=True)

st.markdown("---")
st.subheader("Descargar series")
st.download_button("CSV de salida", out.to_csv(index=False).encode("utf-8"), file_name="series_generadas.csv", mime="text/csv")

st.caption("Fórmulas: ARS real = sueldo_nominal_ars × (CPI_AR_base / CPI_AR_t).  USD real = (sueldo_nominal_ars / TC_t) × (CPI_US_base / CPI_US_t). Base: último mes del rango (editable).")

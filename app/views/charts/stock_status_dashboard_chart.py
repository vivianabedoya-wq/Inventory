import math
import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

def show_out_of_stock_pie(
    dt: pd.DataFrame,
    *,
    top_n: int = 8,
    title: str = "Out of Stock Items by Category",
    figsize: tuple = (6, 6),    
    fill: bool = False,         
):
    if dt is None or dt.empty:
        st.info("No out-of-stock items.")
        return

    dt = dt.sort_values("items_out_of_stock", ascending=False)
    if len(dt) > top_n:
        top = dt.head(top_n).copy()
        other = dt.iloc[top_n:]["items_out_of_stock"].sum()
        top.loc[len(top)] = ["Other", other]
        dt = top

    labels = dt["category"].astype(str).tolist()
    sizes  = dt["items_out_of_stock"].astype(int).tolist()

    width = 0.38
    inner_r = 1 - width
    r_label = inner_r + width/2

    fig, ax = plt.subplots(figsize=figsize)   
    wedges, _ = ax.pie(
        sizes,
        labels=labels,
        labeldistance=1.05,
        startangle=90,
        wedgeprops={"width": width, "linewidth": 1},
    )
    ax.axis("equal")
    ax.set_title(title)

    for w, v in zip(wedges, sizes):
        if v <= 0: 
            continue
        ang = math.radians((w.theta1 + w.theta2) / 2.0)
        x = r_label * math.cos(ang)
        y = r_label * math.sin(ang)
        ax.text(x, y, str(int(v)), ha="center", va="center")

    st.pyplot(fig, use_container_width=fill) 

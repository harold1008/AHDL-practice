import re
import random
import difflib
import sqlite3
import datetime

import pandas as pd
import streamlit as st

st.set_page_config(page_title="AHDL 默寫練習", layout="wide")

DB_PATH = "records.db"


def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            question TEXT NOT NULL,
            digits TEXT NOT NULL,
            correct INTEGER NOT NULL,
            time TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


conn = init_db()

# 117001：四個數字對應的七段顯示碼 (a,b,c,d,e,f,g)，1=亮
Q1_SEGMENTS = {
    0: (1, 1, 1, 1, 1, 1, 0),
    1: (0, 1, 1, 0, 0, 0, 0),
    2: (1, 1, 0, 1, 1, 0, 1),
    3: (1, 1, 1, 1, 0, 0, 1),
    4: (0, 1, 1, 0, 0, 1, 1),
    5: (1, 0, 1, 1, 0, 1, 1),
    6: (1, 0, 1, 1, 1, 1, 1),
    7: (1, 1, 1, 0, 0, 0, 0),
    8: (1, 1, 1, 1, 1, 1, 1),
    9: (1, 1, 1, 1, 0, 1, 1),
}

# 117002：數字對應的七段顯示 16 進位碼（此電路為 active-low 編碼）
Q2_HEX = {
    0: "01",
    1: "4f",
    2: "12",
    3: "06",
    4: "4c",
    5: "24",
    6: "20",
    7: "0f",
    8: "00",
    9: "0c",
}


def build_117001(digits):
    dsel = [(1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)]
    rows = []
    for i, digit in enumerate(digits):
        seg = Q1_SEGMENTS[digit]
        vals = list(dsel[i]) + list(seg) + [1]
        rows.append(f"{i}=>{','.join(map(str, vals))};")
    return (
        "subdesign 117001 ( clk:input; d1,d2,d3,d4:output; "
        "a,b,c,d,e,f,g,dp:output; ) variable cnt[15..0]:dff; "
        "begin cnt[].clk=!clk; cnt[]=cnt[]+1; "
        "table cnt[15..14]=>d1,d2,d3,d4,a,b,c,d,e,f,g,dp; "
        + " ".join(rows)
        + " end table; end;"
    )


def build_117002(d1, d2):
    hex1, hex2 = Q2_HEX[d1], Q2_HEX[d2]
    return (
        "subdesign 117002 ( clk,colume[2..0] :input; "
        "row[3..0],a,b,c,d,e,f,g : output; ) "
        "variable cnt[17..0],edge[1..0] :dff; disp[6..0] :latch; "
        "begin cnt[].clk=!clk; cnt[]=cnt[]+1; "
        "table cnt[17..16]=>row[3..0]; 0=>1; 1=>2; 2=>4; 3=>8; end table; "
        "edge[].clk=!cnt[11]; "
        "edge[0]=colume[0]#colume[1]#colume[2]; edge[1]=edge[0]; "
        "disp[].ena=edge[0]&!edge[1]; "
        "table row[3..0],colume[2..0]=>disp[]; "
        "1,1=>h\"4f\"; 1,2=>h\"12\"; 1,4=>h\"06\"; "
        "2,1=>h\"4c\"; 2,2=>h\"24\"; 2,4=>h\"20\"; "
        "4,1=>h\"0f\"; 4,2=>h\"00\"; 4,4=>h\"0c\"; "
        f"8,1=>h\"{hex1}\"; 8,2=>h\"01\"; 8,4=>h\"{hex2}\"; "
        "end table; "
        "a=disp[6]; b=disp[5]; c=disp[4]; d=disp[3]; "
        "e=disp[2]; f=disp[1]; g=disp[0]; end;"
    )


QUESTIONS = {
    "117001": {
        "title": "117001 顯示器掃描",
        "explanation": """
**電路功能**：四位數七段顯示器動態掃描

**運作原理**
- `cnt[15..0]` 是一個 16 位元計數器，以反相時脈 `!clk` 觸發，持續累加。
- 取計數器最高兩位 `cnt[15..14]`（數值 0~3）作為掃描狀態，透過 table 對照出：
  - 哪一位數的位選線（`d1`~`d4`）要導通
  - 該位數對應要顯示的七段字型（`a`~`g`, `dp`）
- 因為只用最高兩位，所以每個掃描狀態會維持計數器的低 14 位跑完一輪，掃描速度夠快，
  肉眼因視覺暫留會覺得四位數字是「同時」穩定顯示，其實是輪流快速切換的動態掃描（多工顯示）。
- 檢定時四個數字會隨機指定，需依指定數字自行填入對應的七段字型碼。

**重點觀念**：時脈除頻 + table 對照 + 動態掃描（多工），是七段顯示器常見的省接腳做法。
""",
    },
    "117002": {
        "title": "117002 鍵盤掃描",
        "explanation": """
**電路功能**：4x3 鍵盤矩陣掃描並顯示按鍵數字

**運作原理**
- `cnt[17..0]` 為 18 位元計數器，以反相時脈觸發。取最高兩位 `cnt[17..16]` 透過 table
  以 one-hot 方式輪流驅動 `row[3..0]`（0001→0010→0100→1000），對四條列線做快速掃描。
- `edge[1..0]` 是邊緣偵測用的 2 級移位暫存器，時脈來自 `cnt[11]`（比 row 掃描慢的取樣頻率）：
  - `edge[0]` = 三條欄位線（`colume[0..2]`）做 OR，代表「目前掃描到的列上有任何欄位被按下」
  - `edge[1]` 是 `edge[0]` 延遲一拍的結果
  - `disp[].ena = edge[0] & !edge[1]`：只在訊號由 0 變 1 的瞬間（上升緣）才致能鎖存器，
    避免掃描過程中重複觸發或彈跳（防彈跳/去抖動的簡易做法）。
- 觸發當下的 `row[3..0], colume[2..0]` 組合透過第二個 table 對照出對應的七段字型碼
  （以 16 進位存入 `disp[6..0]`），最後拆解到 `a`~`g` 輸出。
- 檢定時 `8,1` 與 `8,4` 這兩個按鍵對應的數字會隨機指定，需自行填入對應的七段字型碼。

**重點觀念**：row 掃描 + column 讀取 + 邊緣觸發鎖存，是鍵盤矩陣掃描電路的典型結構。
""",
    },
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


def is_correct(correct: str, user_input: str) -> bool:
    return normalize(correct) == normalize(user_input)


def diff_html(correct: str, user_input: str) -> str:
    a, b = normalize(correct), normalize(user_input)
    sm = difflib.SequenceMatcher(None, a, b)
    parts = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            parts.append(a[i1:i2])
        elif tag == "replace":
            parts.append(f"<span style='background:#ffd6d6'>{a[i1:i2]}</span>")
            parts.append(f"<span style='background:#d6ffd6'>{b[j1:j2]}</span>")
        elif tag == "delete":
            parts.append(
                f"<span style='background:#ffd6d6;text-decoration:line-through'>{a[i1:i2]}</span>"
            )
        elif tag == "insert":
            parts.append(f"<span style='background:#d6ffd6'>{b[j1:j2]}</span>")
    return "".join(parts)


def ensure_random(q_id: str):
    if q_id == "117001" and "q1_digits" not in st.session_state:
        st.session_state["q1_digits"] = [random.randint(0, 9) for _ in range(4)]
    if q_id == "117002" and "q2_digits" not in st.session_state:
        st.session_state["q2_digits"] = (random.randint(0, 9), random.randint(0, 9))


st.title("AHDL 默寫練習")

tab1, tab2, tab3 = st.tabs(["默寫模式", "我的紀錄", "程式說明"])

with tab1:
    name = st.text_input("練習者姓名", key="name_input", placeholder="留空則不記錄成績")
    q_id = st.selectbox(
        "選擇題目", list(QUESTIONS.keys()), format_func=lambda x: QUESTIONS[x]["title"]
    )

    ensure_random(q_id)

    reroll = st.button("換一組亂數（重新指定要顯示的數字）")
    if reroll:
        if q_id == "117001":
            st.session_state["q1_digits"] = [random.randint(0, 9) for _ in range(4)]
        else:
            st.session_state["q2_digits"] = (random.randint(0, 9), random.randint(0, 9))
        st.session_state["code_area"] = ""
        st.rerun()

    if q_id == "117001":
        digits = st.session_state["q1_digits"]
        st.info(f"本次要顯示的四個數字（依序對應 d1, d2, d3, d4）：{', '.join(map(str, digits))}")
        correct_code = build_117001(digits)
        digits_label = "-".join(map(str, digits))
    else:
        d1, d2 = st.session_state["q2_digits"]
        st.info(f"本次按鍵 8,1 要顯示的數字：{d1}　按鍵 8,4 要顯示的數字：{d2}")
        correct_code = build_117002(d1, d2)
        digits_label = f"{d1}-{d2}"

    if "code_area" not in st.session_state:
        st.session_state["code_area"] = ""

    user_code = st.text_area("請默寫完整程式碼", height=300, key="code_area")

    col1, col2 = st.columns(2)
    check = col1.button("檢查答案", use_container_width=True)
    clear = col2.button("清空重來", use_container_width=True)

    if clear:
        st.session_state["code_area"] = ""
        st.rerun()

    if check:
        if not user_code.strip():
            st.warning("請先輸入程式碼")
        else:
            correct = is_correct(correct_code, user_code)

            if correct:
                st.success("正確")
            else:
                st.error("不正確")
                st.markdown("**差異對照**（紅底為標準答案中你漏寫或寫錯的部分，綠底為你多寫或寫錯的部分）")
                st.markdown(
                    f"<div style='font-family:monospace;white-space:pre-wrap;"
                    f"word-break:break-all'>{diff_html(correct_code, user_code)}</div>",
                    unsafe_allow_html=True,
                )

            if name.strip():
                conn.execute(
                    "INSERT INTO records (name, question, digits, correct, time) VALUES (?, ?, ?, ?, ?)",
                    (
                        name.strip(),
                        q_id,
                        digits_label,
                        1 if correct else 0,
                        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    ),
                )
                conn.commit()
            else:
                st.info("留空姓名，本次成績不會記錄")

with tab2:
    st.subheader("個人紀錄查詢")
    query_name = st.text_input("輸入姓名查詢", key="query_name")

    if query_name.strip():
        rows = conn.execute(
            "SELECT question, digits, correct, time FROM records WHERE name=? ORDER BY time DESC",
            (query_name.strip(),),
        ).fetchall()

        if rows:
            df = pd.DataFrame(rows, columns=["題目代碼", "隨機數字", "correct", "時間"])
            df["題目"] = df["題目代碼"].map(lambda x: QUESTIONS[x]["title"])
            df["結果"] = df["correct"].map(lambda x: "對" if x == 1 else "錯")

            total = len(df)
            correct_count = int(df["correct"].sum())

            col1, col2, col3 = st.columns(3)
            col1.metric("練習次數", total)
            col2.metric("答對次數", correct_count)
            col3.metric("答錯次數", total - correct_count)

            st.markdown("**詳細紀錄**")
            st.dataframe(
                df[["題目", "隨機數字", "結果", "時間"]],
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("查無此練習者的紀錄")
    else:
        st.caption("輸入姓名以查詢個人練習紀錄")

with tab3:
    st.subheader("程式說明")
    exp_id = st.selectbox(
        "選擇要說明的題目",
        list(QUESTIONS.keys()),
        format_func=lambda x: QUESTIONS[x]["title"],
        key="exp_select",
    )
    st.markdown(QUESTIONS[exp_id]["explanation"])

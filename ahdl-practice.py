import re
import random
import difflib
import sqlite3
import datetime
from html import escape

import pandas as pd
import streamlit as st

st.set_page_config(page_title="AHDL 默寫練習", layout="wide")

DB_PATH = "records.db"


def init_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    existing_cols = [
        r[1] for r in conn.execute("PRAGMA table_info(records)").fetchall()
    ]
    if existing_cols and ("digits" not in existing_cols or "correct" not in existing_cols):
        conn.execute("DROP TABLE records")
        conn.commit()

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

# 117001：數字對應的七段顯示碼 (a,b,c,d,e,f,g)，1=亮
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

# 117002：數字對應的七段顯示 16 進位碼（active-low：位元 0 代表該段點亮）
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

TEMPLATE_117001 = """subdesign 117001
(
    clk:input;
    d1,d2,d3,d4:output;
    a,b,c,d,e,f,g,dp:output;
)
variable
    cnt[15..0]:dff;
begin
    cnt[].clk=!clk;
    cnt[]=cnt[]+1;
    table
        cnt[15..14]=>d1,d2,d3,d4,a,b,c,d,e,f,g,dp;
        {row0}
        {row1}
        {row2}
        {row3}
    end table;
end;"""

TEMPLATE_117002 = """subdesign 117002
(
    clk,colume[2..0]    :input;
    row[3..0],a,b,c,d,e,f,g : output;
)
variable
    cnt[17..0],edge[1..0] :dff;
    disp[6..0] :latch;
begin
    cnt[].clk=!clk;
    cnt[]=cnt[]+1;
    table
        cnt[17..16]=>row[3..0];
        0=>1;
        1=>2;
        2=>4;
        3=>8;
    end table;
    edge[].clk=!cnt[11];
    edge[0]=colume[0]#colume[1]#colume[2];
    edge[1]=edge[0];
    disp[].ena=edge[0]&!edge[1];
    table
        row[3..0],colume[2..0]=>disp[];
        1,1=>h"4f";
        1,2=>h"12";
        1,4=>h"06";
        2,1=>h"4c";
        2,2=>h"24";
        2,4=>h"20";
        4,1=>h"0f";
        4,2=>h"00";
        4,4=>h"0c";
        8,1=>h"{hex1}";
        8,2=>h"01";
        8,4=>h"{hex2}";
    end table;
    a=disp[6];
    b=disp[5];
    c=disp[4];
    d=disp[3];
    e=disp[2];
    f=disp[1];
    g=disp[0];
end;"""


def decode_hex_segments(hex_str: str):
    val = int(hex_str, 16) & 0x7F
    bits = [(val >> i) & 1 for i in range(6, -1, -1)]
    return tuple(bit == 0 for bit in bits)


def build_117001(digits):
    dsel = [(1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)]
    rows = {}
    for i, digit in enumerate(digits):
        seg = Q1_SEGMENTS[digit]
        dp_bit = 0 if i == 2 else 1  # active-low：第 3 位數後方顯示小數點
        vals = list(dsel[i]) + list(seg) + [dp_bit]
        rows[f"row{i}"] = f"{i}=>{','.join(map(str, vals))};"
    return TEMPLATE_117001.format(**rows)


def build_117002(d1, d2):
    return TEMPLATE_117002.format(hex1=Q2_HEX[d1], hex2=Q2_HEX[d2])


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
- 檢定時四個數字會隨機指定，且第 3 位數後方會亮小數點，需依指定的顯示圖案自行填入
  對應的七段字型碼與小數點位元。

**逐行說明**
- `subdesign 117001` — 宣告這個電路模組的名稱。
- `clk:input;` — `clk` 是輸入接腳，提供時脈訊號。
- `d1,d2,d3,d4:output;` — 四個輸出接腳，各自控制四位數顯示器其中一位的「位選線」（哪一位數字要導通顯示）。
- `a,b,c,d,e,f,g,dp:output;` — 八個輸出接腳，對應七段顯示器的七個段與小數點。
- `variable` — 開始宣告內部使用的變數。
- `cnt[15..0]:dff;` — 宣告一個 16 位元暫存器 `cnt`，型態 `dff`（正反器，會依時脈更新並記住狀態）。
- `begin` — 電路邏輯本體開始。
- `cnt[].clk=!clk;` — 把 `cnt` 的時脈接到 `clk` 的反相訊號。
- `cnt[]=cnt[]+1;` — 每次時脈觸發，`cnt` 加 1，形成一個持續累加的計數器。
- `table` — 開始用真值表描述輸出邏輯。
- `cnt[15..14]=>d1,d2,d3,d4,a,b,c,d,e,f,g,dp;` — 宣告這張表格是「輸入 `cnt` 最高兩位」對照「輸出這 12 個訊號」。
- `0=>...;` `1=>...;` `2=>...;` `3=>...;` — 當 `cnt[15..14]` 分別是 0、1、2、3 時，依序輸出對應的位選線與七段字型碼，也就是輪流顯示第 1、2、3、4 位數字。
- `end table;` — 結束真值表。
- `end;` — 結束整個電路描述。

**看題目**
```
subdesign 117001
(
    clk:input;
    d1,d2,d3,d4:output;
    a,b,c,d,e,f,g,dp:output;
)
variable
    cnt[15..0]:dff;
begin
    cnt[].clk=!clk;
    cnt[]=cnt[]+1;
    table
        cnt[15..14]=>d1,d2,d3,d4,a,b,c,d,e,f,g,dp;
        0=>1,0,0,0,0,1,1,0,0,0,0,1;
        1=>0,1,0,0,1,1,0,1,1,0,1,1;
        2=>0,0,1,0,1,1,1,1,0,0,1,1;
        3=>0,0,0,1,0,0,0,0,0,0,0,1;
    end table;
end;
```
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
- 檢定時 `8,1` 與 `8,4` 這兩個按鍵對應的顯示圖案會隨機指定，需依畫面上的圖案自行填入對應字型碼。

**逐行說明**
- `subdesign 117002` — 宣告這個電路模組的名稱。
- `clk,colume[2..0] :input;` — `clk` 是時脈輸入；`colume[2..0]` 是 3 條欄位線輸入（鍵盤矩陣的「欄」）。
- `row[3..0],a,b,c,d,e,f,g : output;` — `row[3..0]` 是 4 條列線輸出（鍵盤矩陣的「列」，用來掃描）；`a`~`g` 是七段顯示器的七段輸出。
- `variable` — 開始宣告內部使用的變數。
- `cnt[17..0],edge[1..0] :dff;` — `cnt` 是 18 位元計數器，當作列掃描的時基；`edge` 是 2 位元暫存器，用來偵測按鍵訊號的上升緣。
- `disp[6..0] :latch;` — `disp` 是 7 位元鎖存器，用來鎖住目前要顯示的七段字型碼。
- `begin` — 電路邏輯本體開始。
- `cnt[].clk=!clk;` — `cnt` 的時脈接反相 `clk`。
- `cnt[]=cnt[]+1;` — `cnt` 持續累加，形成計數器。
- 第一個 `table ... end table;` — 用 `cnt` 最高兩位（`cnt[17..16]`）決定 `row[3..0]` 的輸出，依序是 1、2、4、8（one-hot，每次只有一條列線為高電位），達成輪流掃描四條列線的效果。
- `edge[].clk=!cnt[11];` — `edge` 暫存器的時脈取自 `cnt[11]`，是比列掃描慢的取樣頻率，用來取樣按鍵狀態。
- `edge[0]=colume[0]#colume[1]#colume[2];` — `edge[0]` 等於三條欄位線做 OR（邏輯或），只要任一欄位線為高電位，`edge[0]` 就是 1，代表偵測到有按鍵反應。
- `edge[1]=edge[0];` — `edge[1]` 是 `edge[0]` 延遲一個時脈的結果，用來跟 `edge[0]` 比較是否剛好在這一拍「由 0 變 1」。
- `disp[].ena=edge[0]&!edge[1];` — 只有在 `edge[0]=1` 且 `edge[1]=0`（代表剛好是上升緣的那一瞬間）時，才致能 `disp` 鎖存器去鎖住當下的按鍵資料，避免重複觸發或彈跳。
- 第二個 `table ... end table;` — 用「目前的 `row` 與 `colume` 組合」對照出對應的七段字型碼（16 進位），鎖存進 `disp`。
- `a=disp[6];` ~ `g=disp[0];` — 把鎖存器 `disp` 的 7 個位元，依序拆解接到 `a`~`g` 七個輸出接腳，實際點亮對應的七段顯示器。
- `end;` — 結束整個電路描述。

**看題目**
```
subdesign 117002
(
    clk,colume[2..0]    :input;
    row[3..0],a,b,c,d,e,f,g : output;
)
variable
    cnt[17..0],edge[1..0] :dff;
    disp[6..0] :latch;
begin
    cnt[].clk=!clk;
    cnt[]=cnt[]+1;
    table
        cnt[17..16]=>row[3..0];
        0=>1;
        1=>2;
        2=>4;
        3=>8;
    end table;
    edge[].clk=!cnt[11];
    edge[0]=colume[0]#colume[1]#colume[2];
    edge[1]=edge[0];
    disp[].ena=edge[0]&!edge[1];
    table
        row[3..0],colume[2..0]=>disp[];
        1,1=>h"4f";
        1,2=>h"12";
        1,4=>h"06";
        2,1=>h"4c";
        2,2=>h"24";
        2,4=>h"20";
        4,1=>h"0f";
        4,2=>h"00";
        4,4=>h"0c";
        8,1=>h"72";
        8,2=>h"01";
        8,4=>h"66";
    end table;
    a=disp[6];
    b=disp[5];
    c=disp[4];
    d=disp[3];
    e=disp[2];
    f=disp[1];
    g=disp[0];
end;
```
""",
    },
}


def normalize(text: str) -> str:
    return re.sub(r"\s+", "", text)


def is_correct(correct: str, user_input: str) -> bool:
    return normalize(correct) == normalize(user_input)


def line_diff_html(correct_code: str, user_code: str) -> str:
    """逐行比對，單一行錯誤只標示那一行，不影響其他行的判定"""
    correct_lines = correct_code.split("\n")
    correct_norm_lines = [normalize(line) for line in correct_lines]
    user_norm_lines = [
        normalize(line) for line in user_code.split("\n") if line.strip() != ""
    ]

    line_ok = [False] * len(correct_lines)
    sm = difflib.SequenceMatcher(None, correct_norm_lines, user_norm_lines)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i1, i2):
                line_ok[k] = True

    html_lines = []
    for i, line in enumerate(correct_lines):
        if line_ok[i]:
            html_lines.append(
                f"<div style='color:#e5e5e7;white-space:pre'>{escape(line)}</div>"
            )
        else:
            html_lines.append(
                f"<div style='color:#ff6961;font-weight:600;white-space:pre'>{escape(line)}</div>"
            )

    return (
        "<div style='font-family:monospace;background:#1c1c1e;padding:14px;"
        "border-radius:8px;line-height:1.6'>" + "".join(html_lines) + "</div>"
    )


# ---------- 七段顯示器繪圖 ----------

SEG_ON_COLOR = "#ff3b30"
SEG_OFF_COLOR = "#3a3a3c"
DIGIT_W, DIGIT_H, STROKE, GAP = 46, 84, 9, 26


def _digit_svg(segments, dp_on, x_offset):
    a, b, c, d, e, f, g = segments
    tl, tr = (x_offset, 0), (x_offset + DIGIT_W, 0)
    ml, mr = (x_offset, DIGIT_H / 2), (x_offset + DIGIT_W, DIGIT_H / 2)
    bl, br = (x_offset, DIGIT_H), (x_offset + DIGIT_W, DIGIT_H)
    segs = [
        (tl, tr, a),
        (tr, mr, b),
        (mr, br, c),
        (bl, br, d),
        (ml, bl, e),
        (tl, ml, f),
        (ml, mr, g),
    ]
    lines = []
    for p1, p2, on in segs:
        color = SEG_ON_COLOR if on else SEG_OFF_COLOR
        lines.append(
            f"<line x1='{p1[0]}' y1='{p1[1]}' x2='{p2[0]}' y2='{p2[1]}' "
            f"stroke='{color}' stroke-width='{STROKE}' stroke-linecap='round'/>"
        )
    dp_color = SEG_ON_COLOR if dp_on else SEG_OFF_COLOR
    lines.append(
        f"<circle cx='{x_offset + DIGIT_W + 9}' cy='{DIGIT_H}' r='5' fill='{dp_color}'/>"
    )
    return "".join(lines)


def render_seven_seg(digit_specs, label=""):
    total_w = len(digit_specs) * (DIGIT_W + GAP) + 10
    body = "".join(
        _digit_svg(segs, dp, 10 + i * (DIGIT_W + GAP))
        for i, (segs, dp) in enumerate(digit_specs)
    )
    caption = (
        f"<div style='color:#9a9a9e;font-size:13px;margin-bottom:6px'>{label}</div>"
        if label
        else ""
    )
    svg = (
        f"<div style='display:inline-block;background:#1c1c1e;border-radius:10px;"
        f"padding:14px 18px;margin:4px 10px 4px 0'>{caption}"
        f"<svg width='{total_w}' height='{DIGIT_H + 12}' "
        f"viewBox='0 0 {total_w} {DIGIT_H + 12}' xmlns='http://www.w3.org/2000/svg'>{body}</svg>"
        f"</div>"
    )
    return svg


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

    reroll = st.button("換一組")
    if reroll:
        if q_id == "117001":
            st.session_state["q1_digits"] = [random.randint(0, 9) for _ in range(4)]
        else:
            st.session_state["q2_digits"] = (random.randint(0, 9), random.randint(0, 9))
        st.session_state["code_area"] = ""
        st.rerun()

    st.markdown("**本次題目**")

    if q_id == "117001":
        digits = st.session_state["q1_digits"]
        specs = [
            (tuple(v == 1 for v in Q1_SEGMENTS[d]), i == 2) for i, d in enumerate(digits)
        ]
        st.markdown(render_seven_seg(specs), unsafe_allow_html=True)
        correct_code = build_117001(digits)
        digits_label = "-".join(map(str, digits))
    else:
        d1, d2 = st.session_state["q2_digits"]
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown(
                render_seven_seg([(decode_hex_segments(Q2_HEX[d1]), False)], "按鍵 8,1"),
                unsafe_allow_html=True,
            )
        with col_b:
            st.markdown(
                render_seven_seg([(decode_hex_segments(Q2_HEX[d2]), False)], "按鍵 8,4"),
                unsafe_allow_html=True,
            )
        correct_code = build_117002(d1, d2)
        digits_label = f"{d1}-{d2}"

    if "code_area" not in st.session_state:
        st.session_state["code_area"] = ""

    user_code = st.text_area("請默寫完整程式碼", height=320, key="code_area")

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
                st.markdown("**對照（紅字為該行有誤，其餘行不受影響）**")
                st.markdown(
                    line_diff_html(correct_code, user_code), unsafe_allow_html=True
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

            for qid, qinfo in QUESTIONS.items():
                sub = df[df["題目代碼"] == qid]
                q_total = len(sub)
                q_correct = int(sub["correct"].sum())
                st.markdown(f"**{qinfo['title']}**")
                c1, c2, c3 = st.columns(3)
                c1.metric("練習次數", q_total)
                c2.metric("答對次數", q_correct)
                c3.metric("答錯次數", q_total - q_correct)

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

import streamlit as st
import feedparser
import google.generativeai as genai
import os
import urllib.parse
from bs4 import BeautifulSoup
import email.utils
from datetime import datetime, timezone, timedelta
import re

# --- 1. 페이지 기본 설정 ---
st.set_page_config(page_title="GPA 뉴스 센싱 대시보드", page_icon="📰", layout="wide")
st.title("📰 글로벌 대외협력(GPA) 뉴스 센싱 대시보드")

# --- 2. 사이드바 (키워드/언론사 영구 세팅) ---
with st.sidebar:
    st.header("⚙️ 대시보드 설정")
    st.markdown("<p style='font-size: 14px; color: #ff4b4b;'>🚨 <b>영구 저장 안내:</b><br>다음에 접속할 때도 유지하려면 웹화면이 아니라 <b>깃허브 app.py 코드의 21, 22번째 줄을 직접 수정</b>해야 합니다!</p>", unsafe_allow_html=True)

    # 👇 [수정 위치] 평생 남길 키워드나 도메인은 무조건 아래 큰따옴표 안에 추가하세요!
    DEFAULT_KW = "Trump AI, AI Chips, Anthropic, OpenAI, Bondi, David Sacks, AI Order, Glasswing, OpenAI TAC, Trusted Access for Cyber, AI Exports Program, AI Exports, AI Export, Pax Silica"
    DEFAULT_DOMAINS = "wsj.com, ft.com, bloomberg.com, reuters.com, politico.com, washingtonpost.com, axios.com"

    if "kw_input" not in st.session_state:
        st.session_state.kw_input = DEFAULT_KW
    if "domain_input" not in st.session_state:
        st.session_state.domain_input = DEFAULT_DOMAINS

    user_kw = st.text_area("🔍 검색 키워드 목록 (오늘 하루만 적용)", key="kw_input", height=150)
    user_domains = st.text_area("🌐 탐색할 언론사 사이트 (오늘 하루만 적용)", key="domain_input", height=100)

    if st.button("💾 임시 적용", use_container_width=True):
        st.cache_data.clear() 
        st.rerun()

KEYWORDS = [kw.strip() for kw in st.session_state.kw_input.split(",") if kw.strip()]
TARGET_DOMAINS = [domain.strip() for domain in st.session_state.domain_input.split(",") if domain.strip()]

# --- 3. AI 설정 (자동 탐색 복구 + 필터 해제) ---
api_key = os.environ.get("GEMINI_API_KEY")
model = None

if not api_key:
    st.error("⚠️ 좌측 [Secrets] 메뉴에서 `GEMINI_API_KEY`를 먼저 설정해주세요!")
else:
    genai.configure(api_key=api_key)
    try:
        # 내 버전에 맞는 정확한 모델 풀네임을 알아서 찾아오는 로직 부활
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        target_model_name = next((m for m in available_models if '1.5-flash' in m), None)
        if not target_model_name:
            target_model_name = next((m for m in available_models if 'pro' in m), available_models[0])
        model = genai.GenerativeModel(target_model_name)
    except Exception as e:
        st.sidebar.error(f"모델 탐색 에러: {e}")

# --- 4. 뉴스 수집 엔진 (Chunking 기술 적용) ---
@st.cache_data(ttl=1800)
def fetch_news(current_keywords, current_domains):
    if not current_keywords or not current_domains:
        return []

    valid_entries = []
    
    # 🚨 구글 검색어 한도 초과 방지: 키워드를 4개씩 한 묶음으로 쪼개기
    chunk_size = 4
    kw_chunks = [current_keywords[i:i + chunk_size] for i in range(0, len(current_keywords), chunk_size)]

    for domain in current_domains:
        for chunk in kw_chunks:
            query_parts = [f'"{kw}"' for kw in chunk]
            kw_query = " OR ".join(query_parts)
            
            full_query = f"({kw_query}) site:{domain} when:48h"
            encoded_query = urllib.parse.quote(full_query)
            rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
            
            feed = feedparser.parse(rss_url)

            for entry in feed.entries:
                title = entry.title if hasattr(entry, 'title') else ""
                desc = entry.description if hasattr(entry, 'description') else ""
                text_to_search = (title + " " + desc).lower()
                matched_tags = []

                # 가져온 기사 안에 전체 키워드 중 일치하는 게 있는지 꼼꼼히 재검사
                for kw in current_keywords:
                    words = kw.lower().split()
                    if all(re.search(rf'\b{re.escape(word)}\b', text_to_search) for word in words):
                        matched_tags.append(f"#{kw.replace(' ', '_')}")

                # 중복 수집 방지
                if matched_tags and not any(e.link == entry.link for e in valid_entries):
                    entry.matched_tags = list(set(matched_tags)) 
                    valid_entries.append(entry)

    def get_timestamp(e):
        try:
            return email.utils.parsedate_to_datetime(e.published).timestamp()
        except:
            return 0.0 

    valid_entries.sort(key=get_timestamp, reverse=True)
    return valid_entries

# AI 에러 방어 및 검열 해제 로직
def ai_news_summarizer(title, description):
    safe_description = description[:1500] 
    prompt = f"""
    다음은 미국 테크/정책 뉴스의 제목과 본문 일부입니다. 
    대외협력(GPA) 부서에서 글로벌 동향 파악을 위해 참고할 수 있도록 핵심만 3줄로 한국어로 요약해 주세요.

    제목: {title}
    내용: {safe_description}
    """
    
    safety_settings = [
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
    ]

    try:
        response = model.generate_content(prompt, safety_settings=safety_settings)
        if response.text:
            return response.text
    except Exception as e:
        return f"⚠️ 구글 AI 요약 실패 (에러 상세 원인): {e}"

# --- 5. 화면 출력 ---
st.subheader("📡 글로벌 매체 실시간 센싱 결과 (최근 48시간)")

if not KEYWORDS or not TARGET_DOMAINS:
    st.warning("👈 좌측 사이드바에서 검색할 키워드와 언론사 도메인을 최소 1개 이상 입력해 주세요.")
else:
    entries = fetch_news(KEYWORDS, TARGET_DOMAINS)

    if not entries:
        st.info("지정된 키워드로 최근 48시간 내에 검색된 뉴스가 없습니다.")
    else:
        st.success(f"⭐ 지정한 매체에서 조건에 완벽히 일치하는 {len(entries)}개의 뉴스를 발견했습니다.")

        for entry in entries: 
            title = entry.title
            link = entry.link
            published = entry.published
            source = entry.source.title if hasattr(entry, 'source') else "Unknown"
            description = entry.description if hasattr(entry, 'description') else ""

            try:
                dt = email.utils.parsedate_to_datetime(published)
                kst_tz = timezone(timedelta(hours=9))
                formatted_date = dt.astimezone(kst_tz).strftime("%m월 %d일 %H:%M (KST)")
            except:
                formatted_date = published 

            source_display = f"⭐ **{source}**"
            hashtag_display = " ".join(entry.matched_tags)

            col1, col2 = st.columns([4, 1])
            with col1:
                st.markdown(f"#### {source_display} | {title}")
                st.markdown(f"<p style='color: #deff9a; font-weight: bold; margin-top: -10px; margin-bottom: 15px;'>{hashtag_display}</p>", unsafe_allow_html=True)
            with col2:
                st.markdown(f"<p style='text-align: right; color: gray; font-size: 14px; margin-top: 5px;'>{formatted_date}</p>", unsafe_allow_html=True)

            if link not in st.session_state:
                st.session_state[link] = ""

            if api_key and model:
                if not st.session_state[link]:
                    if st.button("🤖 AI 3줄 요약 보기", key=f"btn_{link}"):
                        soup = BeautifulSoup(description, "html.parser")
                        clean_text = soup.get_text()
                        with st.spinner("요약 중입니다..."):
                            st.session_state[link] = ai_news_summarizer(title, clean_text)
                            st.rerun() 

            if st.session_state[link]:
                st.markdown(f"<div style='background-color: #262730; padding: 15px; border-radius: 10px; border-left: 5px solid #deff9a; margin-bottom: 10px;'>{st.session_state[link]}</div>", unsafe_allow_html=True)

            st.markdown(f"🔗 [기사 원문 보러가기]({link})")
            st.divider()

# --- 6. 수동 새로고침 ---
if st.button("🔄 최신 뉴스 다시 불러오기"):
    fetch_news.clear() 
    st.rerun()

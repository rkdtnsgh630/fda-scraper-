import os
from datetime import datetime, timedelta
import time
import traceback

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from google.oauth2 import service_account
from googleapiclient.discovery import build

# ──────────────── 설정 ──────────────── #
SERVICE_ACCOUNT_FILE = 'service_account_credentials.json'
SPREADSHEET_ID = '1L_sPHkWw6nzVWCFUXnTVUuCNyJjogmyM90iFCIvluD8'
SHEET_NAME = 'FDA_WL'
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
FILTER_KEYWORD = 'Finished Pharmaceuticals'
INITIAL_LOOK_BACK_YEARS = 3
MAX_PAGES = 50
# ───────────────────────────────────── #

# Actions 환경: GOOGLE_CREDENTIALS 시크릿으로 credentials.json 파일 생성
if os.getenv("GOOGLE_CREDENTIALS"):
    with open(SERVICE_ACCOUNT_FILE, "w") as f:
        f.write(os.getenv("GOOGLE_CREDENTIALS"))

# --- Google Sheets API 인증 ---
try:
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    sheet_service = build('sheets', 'v4', credentials=credentials)
    sheet = sheet_service.spreadsheets()
    print("✅ 구글 시트 인증 성공")
except Exception as e:
    print(f"❌ 구글 시트 인증 실패: {e}")
    exit()


# --- 기준 날짜 계산 함수 ---
def parse_date(date_str):
    for fmt in ('%B %d, %Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except (ValueError, TypeError):
            continue
    return None


# --- Selenium 웹 드라이버 설정 ---
options = webdriver.ChromeOptions()
options.add_argument('--headless')
options.add_argument('--disable-blink-features=AutomationControlled')
options.add_argument('--disable-gpu')
options.add_argument('--no-sandbox')
options.add_argument('--disable-dev-shm-usage')
options.add_argument("--window-size=1920,1080")
options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option('useAutomationExtension', False)

print("🖥️ 웹 드라이버 실행 시작")
driver = webdriver.Chrome(service=Service(), options=options)
driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
wait = WebDriverWait(driver, 20)


def save_debug_info(name_prefix):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    with open(f'{name_prefix}_page_{timestamp}.html', 'w', encoding='utf-8') as f:
        f.write(driver.page_source)
    driver.save_screenshot(f'{name_prefix}_screenshot_{timestamp}.png')
    print(f"📸 스크린샷 저장됨: {name_prefix}_screenshot_{timestamp}.png")
    print(f"📄 HTML 저장됨: {name_prefix}_page_{timestamp}.html")

try:
    #########################################################################
    # 1부: 새로운 Warning Letter 목록 수집 및 시트 추가
    #########################################################################
    print("\n" + "=" * 20 + " 1부: 신규 목록 수집 시작 " + "=" * 20)

    print("📊 구글 시트에서 마지막 날짜를 가져오는 중...")
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'{SHEET_NAME}!A2:A2').execute()
    values = result.get('values', [])
    if values and values[0]:
        most_recent_saved_date = parse_date(values[0][0])
        start_date = most_recent_saved_date - timedelta(days=2)
        print(f"🔄 마지막 저장 날짜({most_recent_saved_date.strftime('%Y-%m-%d')}) 이후의 새로운 데이터를 확인합니다.")
    else:
        start_date = datetime.now() - timedelta(days=365 * INITIAL_LOOK_BACK_YEARS)
        print(f"🚀 첫 실행입니다. 약 {INITIAL_LOOK_BACK_YEARS}년 전의 데이터부터 수집을 시작합니다.")
    date_str_set = set(
        (start_date + timedelta(days=i)).strftime('%m/%d/%Y') for i in range((datetime.now() - start_date).days + 1))
    print(f"📅 데이터 검색 범위: {start_date.strftime('%Y-%m-%d')} 부터 오늘까지")

    base_url = 'https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/compliance-actions-and-activities/warning-letters'
    try:
        driver.get(base_url)
    except Exception as e:
        print("❌ 페이지 초기 로딩 실패:", e)
        save_debug_info("initial_load")
        raise

    try:
        search_input = wait.until(EC.visibility_of_element_located((By.ID, 'edit-search-api-fulltext')))
        search_input.send_keys(FILTER_KEYWORD)
        time.sleep(4)
        info_element = wait.until(EC.visibility_of_element_located((By.ID, 'datatable_info')))
        print(f"📊 검색 정보: {info_element.text}")
    except Exception as e:
        print("❌ 페이지 요소 탐색 실패:", e)
        save_debug_info("element_error")
        raise

    collected_rows = []
    for page in range(1, MAX_PAGES + 1):
        print(f"📄 페이지 {page} 처리 중...")
        try:
            table_body = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "#datatable > tbody")))
            rows = table_body.find_elements(By.TAG_NAME, "tr")
        except Exception as e:
            print(f"❌ 테이블 로딩 실패: {e}")
            save_debug_info("table_error")
            break

        if len(rows) == 1 and "No matching records found" in rows[0].text:
            break

        for row in rows:
            cols = row.find_elements(By.TAG_NAME, 'td')
            if len(cols) < 5: continue
            posted_date = cols[0].text.strip()
            if posted_date in date_str_set:
                issue_date = cols[1].text.strip()
                company_name = cols[2].text.strip()
                subject = cols[4].text.strip()
                try:
                    link = cols[2].find_element(By.TAG_NAME, 'a').get_attribute('href')
                except NoSuchElementException:
                    link = ''
                print(f"  -> 목록 수집: {posted_date}, {company_name}")
                collected_rows.append([posted_date, issue_date, company_name, subject, link])

        # 다음 페이지 이동
        try:
            pagination_info_element = driver.find_element(By.ID, "datatable_paginate")
            if 'class="paginate_button page-item next disabled"' in pagination_info_element.get_attribute('innerHTML'):
                print("마지막 페이지에 도달했습니다."); break
            driver.execute_script("jQuery('#datatable').DataTable().page('next').draw('page');")
            time.sleep(3)
        except Exception as e:
            print(f"페이지 이동 중 오류 발생: {e}"); break

    # 중복 제거 및 시트 저장
    if collected_rows:
        existing_links_result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'{SHEET_NAME}!E2:E').execute()
        existing_links = set(row[0] for row in existing_links_result.get('values', []) if row)
        new_rows = [row for row in collected_rows if row[4] not in existing_links]
        if new_rows:
            body = {'values': new_rows}
            sheet.values().append(spreadsheetId=SPREADSHEET_ID, range=f'{SHEET_NAME}!A2',
                                  valueInputOption='RAW', insertDataOption='INSERT_ROWS',
                                  body=body).execute()
            print(f"✅ 1부: 구글 시트에 {len(new_rows)}개 행 추가 완료")
        else:
            print("📭 1부: 저장할 새로운 목록이 없습니다.")
    else:
        print("📭 1부: 새로 추가할 목록이 없습니다.")

    print("=" * 20 + " 1부: 신규 목록 수집 완료 " + "=" * 20)

    #########################################################################
    # 2부: 비어있는 'Body Content' 열 채우기
    #########################################################################
    print("\n" + "=" * 20 + " 2부: 본문 내용 채우기 시작 " + "=" * 20)

    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'{SHEET_NAME}!A2:F').execute()
    all_rows = result.get('values', [])

    tasks = []
    for index, row in enumerate(all_rows):
        row_number = index + 2
        if len(row) >= 5 and row[4] and (len(row) < 6 or not row[5]):
            tasks.append({'link': row[4], 'cell': f'F{row_number}'})

    for i, task in enumerate(tasks):
        link = task['link']
        cell = task['cell']
        print(f"({i+1}/{len(tasks)}) 작업 중 -> {link}")
        try:
            driver.get(link)
            body_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.article-body")))
            body_content = body_element.text.strip()
            body = {'values': [[body_content]]}
            sheet.values().update(spreadsheetId=SPREADSHEET_ID, range=f'{SHEET_NAME}!{cell}',
                                  valueInputOption='RAW', body=body).execute()
            print(f"    -> 시트 업데이트 완료: {cell}")
            time.sleep(1)
        except TimeoutException:
            print("    -> 본문 내용 타임아웃. 건너뜁니다.")
        except Exception as e:
            print(f"    -> 알 수 없는 오류 발생: {e}")

    print("✅ 2부: 본문 채우기 작업 완료")

except Exception as e:
    print(f"❌ 알 수 없는 오류 발생: {e}")
    traceback.print_exc()
    save_debug_info("general_error")

finally:
    driver.quit()
    print("🏁 모든 작업 완료!")

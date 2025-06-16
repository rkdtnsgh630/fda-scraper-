import os
import time
from datetime import datetime, timedelta

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

# --- GitHub Actions용 환경변수 기반 인증 파일 생성 ---
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

# --- 날짜 파싱 함수 ---
def parse_date(date_str):
    for fmt in ('%B %d, %Y', '%m/%d/%Y'):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except Exception:
            continue
    return None

# --- WebDriver 설정 ---
options = webdriver.ChromeOptions()
options.add_argument('--headless')
options.add_argument('--disable-blink-features=AutomationControlled')
options.add_experimental_option("excludeSwitches", ["enable-automation"])
options.add_experimental_option('useAutomationExtension', False)
options.add_argument("start-maximized")
driver = webdriver.Chrome(service=Service(), options=options)
driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
print("🖥️ 웹 드라이버 실행 시작")

try:
    print("\n" + "=" * 20 + " 1부: 신규 목록 수집 시작 " + "=" * 20)

    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'{SHEET_NAME}!A2:A2').execute()
    values = result.get('values', [])
    if values and values[0]:
        most_recent_saved_date = parse_date(values[0][0])
        start_date = most_recent_saved_date - timedelta(days=2)
        print(f"🔄 마지막 저장 날짜({most_recent_saved_date.strftime('%Y-%m-%d')}) 이후의 새로운 데이터를 확인합니다.")
    else:
        start_date = datetime.now() - timedelta(days=365 * INITIAL_LOOK_BACK_YEARS)
        print(f"🚀 첫 실행입니다. 약 {INITIAL_LOOK_BACK_YEARS}년 전부터 수집을 시작합니다.")

    date_str_set = set((start_date + timedelta(days=i)).strftime('%m/%d/%Y') for i in range((datetime.now() - start_date).days + 1))
    print(f"📅 데이터 검색 범위: {start_date.strftime('%Y-%m-%d')} 부터 오늘까지")

    base_url = 'https://www.fda.gov/inspections-compliance-enforcement-and-criminal-investigations/compliance-actions-and-activities/warning-letters'
    driver.get(base_url)
    wait = WebDriverWait(driver, 20)

    try:
        search_input = wait.until(EC.visibility_of_element_located((By.ID, 'edit-search-api-fulltext')))
        search_input.send_keys(FILTER_KEYWORD)
        time.sleep(4)
        info_element = wait.until(EC.visibility_of_element_located((By.ID, 'datatable_info')))
        print(f"📊 검색 정보: {info_element.text}")
    except Exception as e:
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        driver.save_screenshot(f"initial_load_screenshot_{timestamp}.png")
        with open(f"initial_load_page_{timestamp}.html", "w", encoding="utf-8") as f:
            f.write(driver.page_source)
        print(f"❌ 페이지 초기 로딩 실패: {e}")
        raise

    collected_rows = []
    for page in range(1, MAX_PAGES + 1):
        print(f"📄 페이지 {page} 처리 중...")
        found = False
        table_body = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "#datatable > tbody")))
        rows = table_body.find_elements(By.TAG_NAME, "tr")

        if len(rows) == 1 and "No matching records found" in rows[0].text:
            break

        for row in rows:
            cols = row.find_elements(By.TAG_NAME, 'td')
            if len(cols) < 5:
                continue
            posted_date = cols[0].text.strip()
            if posted_date in date_str_set:
                found = True
                issue_date = cols[1].text.strip()
                company_name = cols[2].text.strip()
                subject = cols[4].text.strip()
                try:
                    link = cols[2].find_element(By.TAG_NAME, 'a').get_attribute('href')
                except NoSuchElementException:
                    link = ''
                print(f"  -> 목록 수집: {posted_date}, {company_name}")
                collected_rows.append([posted_date, issue_date, company_name, subject, link])

        if not found and page > 1:
            print("수집 대상 날짜의 데이터가 없어 조기 종료합니다.")
            break

        if 'disabled' in driver.find_element(By.CSS_SELECTOR, '#datatable_paginate .next').get_attribute('class'):
            print("마지막 페이지에 도달했습니다.")
            break

        driver.execute_script("jQuery('#datatable').DataTable().page('next').draw('page');")
        time.sleep(3)

    if not collected_rows:
        print("📭 1부: 새로 추가할 목록이 없습니다.")
    else:
        existing_links_result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'{SHEET_NAME}!E2:E').execute()
        existing_links = set(row[0] for row in existing_links_result.get('values', []) if row)
        new_rows = [row for row in collected_rows if row[4] not in existing_links]
        if new_rows:
            sheet.values().append(spreadsheetId=SPREADSHEET_ID, range=f'{SHEET_NAME}!A2', valueInputOption='RAW', insertDataOption='INSERT_ROWS', body={'values': new_rows}).execute()
            print(f"✅ 1부: 구글 시트에 {len(new_rows)}개 행 추가 완료")
        else:
            print("📭 1부: 저장할 새로운 목록이 없습니다.")

    print("=" * 20 + " 1부: 신규 목록 수집 완료 " + "=" * 20)

    print("\n" + "=" * 20 + " 2부: 본문 내용 채우기 시작 " + "=" * 20)
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID, range=f'{SHEET_NAME}!A2:F').execute()
    all_rows = result.get('values', [])

    tasks = []
    for index, row in enumerate(all_rows):
        row_number = index + 2
        if len(row) >= 5 and row[4] and (len(row) < 6 or not row[5]):
            tasks.append({'link': row[4], 'cell': f'F{row_number}'})

    if not tasks:
        print("✅ 모든 행의 본문이 채워져 있습니다.")
    else:
        for i, task in enumerate(tasks):
            print(f"({i + 1}/{len(tasks)}) 작업 중 -> {task['link']}")
            try:
                driver.get(task['link'])
                body_element = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.article-body")))
                body_content = body_element.text.strip()
                sheet.values().update(spreadsheetId=SPREADSHEET_ID, range=f"{SHEET_NAME}!{task['cell']}", valueInputOption='RAW', body={'values': [[body_content]]}).execute()
                print(f"    -> 본문 수집 및 업데이트 완료: {task['cell']}")
                time.sleep(1)
            except TimeoutException:
                print("    -> 본문 로딩 실패: Timeout")
            except Exception as e:
                print(f"    -> 예외 발생: {e}")

        print("✅ 2부: 본문 채우기 작업 완료")

except Exception as e:
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    driver.save_screenshot(f"general_error_screenshot_{timestamp}.png")
    with open(f"general_error_page_{timestamp}.html", "w", encoding="utf-8") as f:
        f.write(driver.page_source)
    print(f"❌ 알 수 없는 오류 발생: {e}")

finally:
    if 'driver' in locals():
        driver.quit()
    print("🏁 모든 작업 완료!")

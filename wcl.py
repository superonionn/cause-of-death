"""WarcraftLogs v2 GraphQL API client.

Handles authentication, report metadata, and event fetching.
Extended from vodreview to pull damage, debuff, and cast events
needed for death/wipe classification.
"""

import os
import re
import sys
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

load_dotenv()

WCL_TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"
WCL_API_URL = "https://www.warcraftlogs.com/api/v2/client"

REPORT_META_QUERY = """
query($code: String!) {
  reportData {
    report(code: $code) {
      startTime
      endTime
      title
      masterData {
        actors(type: "Player") { id name server }
        abilities { gameID name type }
      }
      fights(killType: All) {
        id name startTime endTime kill difficulty
      }
    }
  }
}
"""

EVENTS_QUERY = """
query($code: String!, $startTime: Float!, $endTime: Float!, $dataType: EventDataType!) {
  reportData {
    report(code: $code) {
      events(dataType: $dataType, startTime: $startTime, endTime: $endTime, limit: 10000) {
        data
        nextPageTimestamp
      }
    }
  }
}
"""

FIGHT_EVENTS_QUERY = """
query($code: String!, $fightIDs: [Int]!, $dataType: EventDataType!, $filterExpression: String) {
  reportData {
    report(code: $code) {
      events(dataType: $dataType, fightIDs: $fightIDs, limit: 10000, filterExpression: $filterExpression) {
        data
        nextPageTimestamp
      }
    }
  }
}
"""

FIGHT_EVENTS_PAGED_QUERY = """
query($code: String!, $fightIDs: [Int]!, $dataType: EventDataType!, $startTime: Float!, $filterExpression: String) {
  reportData {
    report(code: $code) {
      events(dataType: $dataType, fightIDs: $fightIDs, startTime: $startTime, limit: 10000, filterExpression: $filterExpression) {
        data
        nextPageTimestamp
      }
    }
  }
}
"""

DIFFICULTIES = {1: "LFR", 2: "Flex/Normal", 3: "Normal", 4: "Heroic", 5: "Mythic"}


def _wcl_post(token: str, query: str, variables: dict) -> dict:
    r = requests.post(
        WCL_API_URL,
        json={"query": query, "variables": variables},
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    body = r.json()
    if "errors" in body:
        raise RuntimeError(f"WCL API error: {body['errors']}")
    return body["data"]["reportData"]["report"]


def get_token() -> str:
    cid = os.environ.get("WCL_CLIENT_ID")
    cs = os.environ.get("WCL_CLIENT_SECRET")
    if not cid or not cs:
        raise RuntimeError("WCL_CLIENT_ID and WCL_CLIENT_SECRET must be set in .env")
    r = requests.post(
        WCL_TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(cid, cs),
        timeout=10,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def parse_report_code(url: str) -> str:
    m = re.search(r"/reports/([A-Za-z0-9]{16})", url)
    if not m:
        raise ValueError(f"Could not extract report code from URL: {url}")
    return m.group(1)


def fetch_report(token: str, code: str) -> dict:
    return _wcl_post(token, REPORT_META_QUERY, {"code": code})


def fetch_all_events(token: str, code: str, data_type: str, report_end_ms: float) -> list[dict]:
    events = []
    next_ts = 0.0
    while True:
        result = _wcl_post(token, EVENTS_QUERY, {
            "code": code,
            "startTime": next_ts,
            "endTime": report_end_ms,
            "dataType": data_type,
        })
        batch = result["events"]
        events.extend(batch["data"])
        next_ts = batch.get("nextPageTimestamp")
        if next_ts is None:
            break
    return events


def fetch_fight_events(token: str, code: str, fight_ids: list[int], data_type: str,
                       filter_expression: str | None = None) -> list[dict]:
    variables = {
        "code": code,
        "fightIDs": fight_ids,
        "dataType": data_type,
    }
    if filter_expression:
        variables["filterExpression"] = filter_expression

    result = _wcl_post(token, FIGHT_EVENTS_QUERY, variables)
    events = list(result["events"]["data"])
    next_ts = result["events"].get("nextPageTimestamp")

    while next_ts is not None:
        page_vars = {
            "code": code,
            "fightIDs": fight_ids,
            "dataType": data_type,
            "startTime": next_ts,
        }
        if filter_expression:
            page_vars["filterExpression"] = filter_expression
        result = _wcl_post(token, FIGHT_EVENTS_PAGED_QUERY, page_vars)
        events.extend(result["events"]["data"])
        next_ts = result["events"].get("nextPageTimestamp")

    return events


def get_fights_by_boss(report: dict, boss_name: str) -> list[dict]:
    return [f for f in report["fights"] if f["name"] == boss_name]


def get_actors(report: dict) -> dict[int, dict]:
    return {a["id"]: a for a in report["masterData"]["actors"]}


def get_abilities(report: dict) -> dict[int, dict]:
    return {a["gameID"]: a for a in report["masterData"].get("abilities", [])}


def report_start_utc(report: dict) -> datetime:
    return datetime.fromtimestamp(report["startTime"] / 1000, tz=timezone.utc)


PLAYER_DETAILS_QUERY = """
query($code: String!, $fightIDs: [Int]!) {
  reportData {
    report(code: $code) {
      playerDetails(fightIDs: $fightIDs)
    }
  }
}
"""


def get_role_ids(token: str, code: str, fight_ids: list[int]) -> tuple[set[int], set[int]]:
    result = _wcl_post(token, PLAYER_DETAILS_QUERY, {
        "code": code,
        "fightIDs": fight_ids[:1],
    })
    pd = result.get("playerDetails", {})
    if isinstance(pd, dict):
        pd = pd.get("data", {}).get("playerDetails", {})
    tanks = pd.get("tanks", [])
    healers = pd.get("healers", [])
    return {t["id"] for t in tanks}, {h["id"] for h in healers}

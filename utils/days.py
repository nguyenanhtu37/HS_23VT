DAY_ALIASES = {
    "thu2":"monday","th2":"monday","t2":"monday","monday":"monday","mon":"monday",
    "thu3":"tuesday","th3":"tuesday","t3":"tuesday","tuesday":"tuesday","tue":"tuesday",
    "thu4":"wednesday","th4":"wednesday","t4":"wednesday","wednesday":"wednesday","wed":"wednesday",
    "thu5":"thursday","th5":"thursday","t5":"thursday","thursday":"thursday","thu":"thursday",
    "thu6":"friday","th6":"friday","t6":"friday","friday":"friday","fri":"friday",
    "thu7":"saturday","th7":"saturday","t7":"saturday","saturday":"saturday","sat":"saturday",
    "chunhat":"sunday","cn":"sunday","sunday":"sunday","sun":"sunday",
}

def normalize_day(day_text: str) -> str:
    if not day_text:
        return "monday"
    key = day_text.strip().lower().replace(" ", "")
    return DAY_ALIASES.get(key, "monday")
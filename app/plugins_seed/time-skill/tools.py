"""内置插件：时间查询工具"""
import time as _time

from app.tools.registry import tool, tool_result_json


@tool(group="system", name="get_current_time", label="查询当前时间",
      description="获取服务器当前日期时间与星期。当用户询问现在几点/今天日期/星期几时调用。",
      parameters={"type": "object", "properties": {}},
      readonly=True)
def get_current_time():
    t = _time.localtime()
    wd = "一二三四五六日"
    return tool_result_json({
        "ok": True,
        "datetime": _time.strftime("%Y-%m-%d %H:%M:%S", t),
        "weekday": "星期" + wd[t.tm_wday],
    })

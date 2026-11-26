"""Map trusted failure categories to fixed public text; never echo exception data."""


def public_error(error):
    text = str(error)
    categories = (
        (("超时",), "处理超时，请稍后重新提交要求"),
        (("未稳定定位篮筐",), "未稳定定位篮筐，请使用篮筐清晰的固定机位视频"),
        (
            ("模型不存在", "识别模型"),
            "识别模型不存在或不可用，请联系服务管理员检查权重配置",
        ),
        (("模型服务未配置",), "模型服务未配置，请联系服务管理员完成配置"),
        (("模型服务调用失败",), "模型服务调用失败，请稍后重试；已有集锦仍然可用"),
        (("没有可剪辑的可靠进球",), "没有可剪辑的可靠进球，未生成新集锦"),
        (
            ("前后保留时长不能同时为零", "剪辑区间为空"),
            "剪辑区间为空，请增加进球前后保留时长",
        ),
        (
            ("FFmpeg", "导出视频", "视频导出失败"),
            "视频导出失败，请检查视频和 FFmpeg 配置后重试；已有集锦仍然可用",
        ),
        (
            ("检测阶段", "粗扫", "精扫"),
            "视频识别失败，请检查模型配置并使用篮筐清晰的视频",
        ),
    )
    for markers, message in categories:
        if any(marker in text for marker in markers):
            return message
    return "处理失败，请检查模型配置、视频或剪辑要求后重试"

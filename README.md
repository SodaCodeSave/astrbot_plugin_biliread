# 🎬 BiliRead - 让 AI 理解 B 站视频

> AstrBot 插件，让 AI 理解 B 站视频，并给出符合人设的自然回复

![BiliRead](https://github.com/SodaCodeSave/astrbot_plugin_biliread/blob/master/images/PixPin_2026-04-04_11-58-38.png)

## ✨ 功能特性

- 🧠 **深度理解**：不再像传统插件那样使用指令直接发出视频总结，而是通过提取视频字幕，生成总结后返回给AstrBot，让AI给出符合人设的自然回复
- 🛠️ **极简配置**：只需配置 B 站凭据与指定总结模型，开箱即用

## 📦 安装

在 AstrBot 管理后台的 **插件市场** 中搜索 `BiliRead` 直接安装即可。

### 手动安装

1. 在data/plugins目录下执行

    ```bash
    git clone https://github.com/SodaCodeSave/astrbot_plugin_biliread.git
    ```

1. 重启 AstrBot，插件即可生效。

## ⚙️ 配置说明

安装完成后，进入 AstrBot 后台 -> AstrBot 插件 -> 找到 `BiliRead`，需要填写以下内容：

### 1. B站 Cookie

由于 B 站部分视频信息及字幕接口需要登录态，请提供你账号的 Cookie 信息。
插件需要其中的 `SESSDATA` 和 `bili_jct` 字段。

#### 使用浏览器插件获取（适合新手）

1. 安装 [Cookie Editor](https://microsoftedge.microsoft.com/addons/detail/cookieeditor/neaplmfkghagebokkhpjpoebhdledlfi) 浏览器插件。
2. 登录 B 站后，打开 Cookie Editor，找到 `SESSDATA` 和 `bili_jct` 的值，复制。
3. 进入 AstrBot 后台 -> AstrBot 插件 -> 找到 `BiliRead`，将复制的值分别填入插件的对应输入框中。

#### 使用开发者工具获取（适合高手）

1. 在电脑端浏览器登录 [Bilibili](https://www.bilibili.com)。
2. 按 `F12` 打开开发者工具，切换到 `网络` 或 `应用` 标签页。
3. 随便点击一个 B 站的请求，在请求头中找到 `Cookie`。
4. 在一长串字符中找到 `SESSDATA=xxxxxx` 和 `bili_jct=xxxxxx`。
5. 将 `=` 后面的那一串**乱码内容**分别填入插件的对应输入框中。

### 2. 总结视频的AI模型ID (`llm_provider_id`)

指定一个用来“阅读字幕并总结”的 AI 模型。

## 🚀 使用方法

本插件以 **Tool (工具)** 的形式运行，**无需发送特定指令**。

配置完成后，当你与 AstrBot 聊天时，只需发送包含 **B站视频链接** 或 **BV号** 的消息（例如：“看看这个视频 <https://www.bilibili.com/video/BV1GJ411x7h7> ”），AI 就会自动在后台调用 `bilibili_read` 工具获取字幕并进行总结。

## ⚠️ 注意事项 & 常见问题

1. **不是所有视频都有字幕**：如果 UP 主没有上传字幕，且 B 站也没有自动生成 AI 字幕，插件将无法获取内容。此时可能会抛出错误或返回空内容，这属于正常现象。
2. **Cookie 过期问题**：B 站的 `SESSDATA` 有效期通常为几个月。如果突然开始报错（如凭据失效），请尝试重新登录 B 站并更新配置中的 Cookie。
3. **风控拦截**：如果请求过于频繁，B 站可能会触发风控导致请求失败。请勿在短时间内高并发测试。
4. **总结消耗 Token**：由于是将视频字幕喂给大模型，对于超长视频（如几小时的演讲），可能会消耗较多的 Token，建议使用消耗较小的小模型。

## 📜 开源协议

AGPL-3.0 license

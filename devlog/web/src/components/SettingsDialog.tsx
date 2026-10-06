/** 大模型接入设置。
 *
 * 以前要用户自己去 ~/.devlog/config.toml 手写 api_key，等于把零基础用户
 * 直接挡在门外。这里给一个表单：填 key、选模型、测试连接、保存。
 *
 * 两条硬规矩：
 * 1. 已经保存的密钥永远不回显明文，只显示掩码和来源；
 * 2. 输入框留空表示"这一项不改"，否则用户只改模型名就会把 key 抹掉。
 */

import { useEffect, useState } from "react";
import { getLLMConfig, testLLMConfig, updateLLMConfig } from "../api";
import type { LLMConfig, LLMKeySource } from "../types";

function describeSource(source: LLMKeySource): string {
  if (source === "env") {
    return "环境变量 DEEPSEEK_API_KEY";
  }
  if (source === "file") {
    return "本地配置文件";
  }
  return "尚未配置";
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "操作失败，请重试。";
}

export function SettingsDialog({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [config, setConfig] = useState<LLMConfig | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    let cancelled = false;
    getLLMConfig()
      .then((loaded) => {
        if (cancelled) {
          return;
        }
        setConfig(loaded);
        setModel(loaded.model);
        setBaseUrl(loaded.base_url);
      })
      .catch((err) => {
        if (!cancelled) {
          setError(errorText(err));
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  };

  const handleTest = () =>
    run(async () => {
      const result = await testLLMConfig({
        api_key: apiKey,
        base_url: baseUrl,
      });
      if (result.ok) {
        setMessage(result.message);
      } else {
        setError(result.message);
      }
    });

  const handleSave = () =>
    run(async () => {
      const saved = await updateLLMConfig({
        api_key: apiKey,
        model,
        base_url: baseUrl,
      });
      setConfig(saved);
      setApiKey("");
      setMessage("已保存到本机配置文件，AI 功能立即可用。");
      onSaved();
    });

  const handleClear = () =>
    run(async () => {
      const saved = await updateLLMConfig({ clear_api_key: true });
      setConfig(saved);
      setApiKey("");
      setMessage("已清除本机保存的 API Key。");
      onSaved();
    });

  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onClick={(event) => {
        if (event.target === event.currentTarget && !busy) {
          onClose();
        }
      }}
    >
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
      >
        <div className="modal-head">
          <h2 id="settings-title">大模型设置</h2>
          <button
            type="button"
            className="icon-button"
            onClick={onClose}
            disabled={busy}
            aria-label="关闭设置"
            title="关闭"
          >
            ×
          </button>
        </div>

        <p className="form-hint">
          DevLog 只调用兼容 OpenAI 协议的对话接口。Key 只写进你本机的
          配置文件，不进数据库、也不会被提交到任何 Git 仓库。
        </p>

        <div className="settings-status">
          {config === null ? (
            <span>正在读取配置…</span>
          ) : config.configured ? (
            <span>
              已接入：<code>{config.api_key_hint}</code>
              （来源：{describeSource(config.key_source)}）
            </span>
          ) : (
            <span>还没接入大模型：AI 生成、翻译等功能会保持禁用。</span>
          )}
        </div>

        <div className="form-grid">
          <label className="field-label" htmlFor="settings-api-key">
            API Key
          </label>
          <input
            id="settings-api-key"
            type="password"
            autoComplete="off"
            value={apiKey}
            spellCheck={false}
            placeholder={
              config?.api_key_hint
                ? `已保存 ${config.api_key_hint}，留空表示不改动`
                : "粘贴你的 API Key"
            }
            onChange={(event) => setApiKey(event.target.value)}
          />

          <label className="field-label" htmlFor="settings-model">
            模型
          </label>
          <input
            id="settings-model"
            value={model}
            spellCheck={false}
            placeholder="deepseek-v4-flash"
            onChange={(event) => setModel(event.target.value)}
          />

          <label className="field-label" htmlFor="settings-base-url">
            接口地址
          </label>
          <input
            id="settings-base-url"
            value={baseUrl}
            spellCheck={false}
            placeholder="https://api.deepseek.com"
            onChange={(event) => setBaseUrl(event.target.value)}
          />
        </div>

        {error && <p className="error">{error}</p>}
        {message && <p className="success">{message}</p>}

        <div className="modal-actions">
          <button
            type="button"
            className="secondary"
            onClick={handleTest}
            disabled={busy}
          >
            测试连接
          </button>
          <button type="button" onClick={handleSave} disabled={busy}>
            保存
          </button>
          <button
            type="button"
            className="secondary danger"
            onClick={handleClear}
            disabled={busy || config?.key_source !== "file"}
            title={
              config?.key_source === "env"
                ? "当前密钥来自环境变量，请直接修改环境变量"
                : "清除本机配置文件里保存的密钥"
            }
          >
            清除密钥
          </button>
        </div>

        {config?.config_path && (
          <p className="panel-hint">
            配置文件位置：<code>{config.config_path}</code>
          </p>
        )}
      </div>
    </div>
  );
}

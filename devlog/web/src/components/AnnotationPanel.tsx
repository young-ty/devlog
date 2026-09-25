import { useState } from "react";

import type { AnnotationKind, CommitAnnotation } from "../types";

/** 一条 commit 的批注列表 + 新增表单。

 * 主题分组和横向时间线都要让人就着某次提交写批注，两处共用同一个组件，
 * 免得"能写批注"这件事有两套实现、两种样式。
 */

interface AnnotationPanelProps {
  commitHash: string;
  annotations: CommitAnnotation[];
  busy: boolean;
  onAdd: (commitHash: string, kind: AnnotationKind, body: string) => void;
  onDelete: (annotation: CommitAnnotation) => void;
}

export function AnnotationPanel({
  commitHash,
  annotations,
  busy,
  onAdd,
  onDelete,
}: AnnotationPanelProps) {
  const [draftKind, setDraftKind] = useState<AnnotationKind>("note");
  const [draftBody, setDraftBody] = useState("");

  function submit() {
    const body = draftBody.trim();
    if (!body) {
      return;
    }
    onAdd(commitHash, draftKind, body);
    setDraftBody("");
  }

  return (
    <div className="annotation-panel">
      {annotations.length > 0 ? (
        <ul className="annotation-list">
          {annotations.map((item) => (
            <li key={item.id} className="annotation-item">
              <span
                className={
                  item.kind === "decision"
                    ? "badge badge-confirmed"
                    : "badge badge-edited"
                }
              >
                {item.kind === "decision" ? "决策" : "备注"}
              </span>
              <span className="annotation-body">{item.body}</span>
              <button
                className="secondary danger tiny"
                disabled={busy}
                onClick={() => onDelete(item)}
              >
                删除
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="panel-hint">
          还没有批注，记下当时的想法、踩的坑或做出的决定。
        </p>
      )}
      <div className="annotation-form">
        <select
          value={draftKind}
          onChange={(event) =>
            setDraftKind(event.target.value as AnnotationKind)
          }
        >
          <option value="note">备注</option>
          <option value="decision">决策</option>
        </select>
        <input
          placeholder="例如：这里的重试逻辑踩过坑"
          value={draftBody}
          onChange={(event) => setDraftBody(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              submit();
            }
          }}
        />
        <button disabled={busy} onClick={submit}>
          添加批注
        </button>
      </div>
    </div>
  );
}

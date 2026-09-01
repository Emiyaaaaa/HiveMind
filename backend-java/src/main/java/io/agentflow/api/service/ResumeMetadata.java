package io.agentflow.api.service;

import java.util.HashMap;
import java.util.Map;

/** Mirrors {@code app.runtime.resume_context} on the Python worker. */
final class ResumeMetadata {

    static final String RESUME_META_KEY = "_resume";

    private ResumeMetadata() {}

    static Map<String, Object> retry(Integer checkpointIndex) {
        Map<String, Object> payload = new HashMap<>();
        payload.put("mode", "retry");
        if (checkpointIndex != null) {
            payload.put("checkpoint_index", checkpointIndex);
        }
        return Map.of(RESUME_META_KEY, payload);
    }

    static Map<String, Object> resume(
            Integer checkpointIndex, Map<String, Object> humanInput) {
        Map<String, Object> payload = new HashMap<>();
        payload.put("mode", "resume");
        if (checkpointIndex != null) {
            payload.put("checkpoint_index", checkpointIndex);
        }
        if (humanInput != null && !humanInput.isEmpty()) {
            payload.put("human_input", humanInput);
        }
        return Map.of(RESUME_META_KEY, payload);
    }

    static Map<String, Object> withoutResume(Map<String, Object> metadata) {
        if (metadata == null || !metadata.containsKey(RESUME_META_KEY)) {
            return metadata == null ? new HashMap<>() : new HashMap<>(metadata);
        }
        Map<String, Object> cleaned = new HashMap<>(metadata);
        cleaned.remove(RESUME_META_KEY);
        return cleaned;
    }

    static void mergeInto(Map<String, Object> metadata, Map<String, Object> resumeBlock) {
        metadata.putAll(withoutResume(metadata));
        metadata.putAll(resumeBlock);
    }
}

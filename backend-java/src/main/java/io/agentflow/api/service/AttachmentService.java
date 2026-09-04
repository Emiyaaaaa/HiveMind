package io.agentflow.api.service;

import io.agentflow.api.config.AgentflowProperties;
import io.agentflow.api.dto.AttachmentResponse;
import io.agentflow.api.entity.AttachmentEntity;
import io.agentflow.api.repository.AttachmentRepository;
import io.agentflow.api.security.AccessControl;
import io.agentflow.api.security.Role;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.multipart.MultipartFile;

@Service
public class AttachmentService {

    private final AttachmentRepository attachments;
    private final AgentflowProperties props;

    public AttachmentService(AttachmentRepository attachments, AgentflowProperties props) {
        this.attachments = attachments;
        this.props = props;
    }

    @Transactional
    public AttachmentResponse upload(MultipartFile file, String caption) {
        AccessControl.require(Role.OPERATOR);
        String tenantId = AccessControl.tenantId(Role.OPERATOR);
        byte[] data;
        try {
            data = file.getBytes();
        } catch (IOException ex) {
            throw new IllegalArgumentException("Failed to read upload", ex);
        }
        if (data.length == 0) {
            throw new IllegalArgumentException("empty attachment");
        }
        long maxBytes = props.getAttachments().getMaxBytes();
        if (data.length > maxBytes) {
            throw new AttachmentTooLargeException(data.length, maxBytes);
        }

        AttachmentEntity entity = new AttachmentEntity();
        entity.setTenantId(tenantId);
        entity.setMediaType(
                file.getContentType() == null || file.getContentType().isBlank()
                        ? "application/octet-stream"
                        : file.getContentType());
        entity.setFilename(
                file.getOriginalFilename() == null || file.getOriginalFilename().isBlank()
                        ? "blob"
                        : Path.of(file.getOriginalFilename()).getFileName().toString());
        entity.setSizeBytes(data.length);
        entity.setSha256(sha256Hex(data));
        entity.setCaption(caption);
        entity.setStorageKey("pending");
        AttachmentEntity saved = attachments.save(entity);

        String key = storageKey(tenantId, saved.getId(), saved.getFilename());
        writeBlob(key, data);
        saved.setStorageKey(key);
        return AttachmentResponse.fromEntity(attachments.save(saved));
    }

    @Transactional(readOnly = true)
    public AttachmentResponse getMeta(String id) {
        return AttachmentResponse.fromEntity(require(id, Role.VIEWER));
    }

    @Transactional(readOnly = true)
    public LoadedAttachment getContent(String id) {
        AttachmentEntity entity = require(id, Role.VIEWER);
        Path path = resolveKey(entity.getStorageKey());
        if (!Files.isRegularFile(path)) {
            throw new AttachmentNotFoundException(id);
        }
        try {
            return new LoadedAttachment(entity, Files.readAllBytes(path));
        } catch (IOException ex) {
            throw new AttachmentNotFoundException(id);
        }
    }

    @Transactional
    public void bindInputAttachments(String runId, String tenantId, Map<String, Object> input) {
        List<String> ids = extractAttachmentIds(input);
        for (String attachmentId : ids) {
            AttachmentEntity entity = attachments
                    .findByIdAndTenantId(attachmentId, tenantId)
                    .orElseThrow(() -> new AttachmentNotFoundException(attachmentId));
            if (entity.getRunId() != null && !entity.getRunId().equals(runId)) {
                throw new AttachmentNotFoundException(attachmentId);
            }
            entity.setRunId(runId);
            attachments.save(entity);
        }
    }

    @Transactional
    public long eraseRun(String runId) {
        List<AttachmentEntity> rows = attachments.findByRunId(runId);
        for (AttachmentEntity row : rows) {
            deleteBlobQuietly(row.getStorageKey());
        }
        return attachments.deleteByRunId(runId);
    }

    @Transactional
    public long eraseTenant(String tenantId) {
        List<AttachmentEntity> rows = attachments.findByTenantId(tenantId);
        for (AttachmentEntity row : rows) {
            deleteBlobQuietly(row.getStorageKey());
        }
        return attachments.deleteByTenantId(tenantId);
    }

    private AttachmentEntity require(String id, Role role) {
        AccessControl.require(role);
        String tenantId = AccessControl.tenantId(role);
        return attachments
                .findByIdAndTenantId(id, tenantId)
                .orElseThrow(() -> new AttachmentNotFoundException(id));
    }

    @SuppressWarnings("unchecked")
    private static List<String> extractAttachmentIds(Map<String, Object> input) {
        if (input == null) {
            return List.of();
        }
        Object raw = input.get("attachments");
        if (!(raw instanceof List<?> list) || list.isEmpty()) {
            return List.of();
        }
        List<String> ids = new ArrayList<>();
        for (Object item : list) {
            if (item instanceof String s) {
                ids.add(s);
            } else if (item instanceof Map<?, ?> map) {
                Object id = map.get("id");
                if (id instanceof String sid) {
                    ids.add(sid);
                }
            }
        }
        return ids;
    }

    private void writeBlob(String key, byte[] data) {
        Path path = resolveKey(key);
        try {
            Files.createDirectories(path.getParent());
            Files.write(path, data);
        } catch (IOException ex) {
            throw new IllegalStateException("Failed to store attachment", ex);
        }
    }

    private void deleteBlobQuietly(String key) {
        try {
            Files.deleteIfExists(resolveKey(key));
        } catch (IOException ignored) {
            // best-effort
        }
    }

    private Path resolveKey(String key) {
        Path root = Path.of(props.getAttachments().getStorageDir()).toAbsolutePath().normalize();
        Path resolved = root.resolve(key).normalize();
        if (!resolved.startsWith(root)) {
            throw new IllegalArgumentException("invalid storage key");
        }
        return resolved;
    }

    private static String storageKey(String tenantId, String attachmentId, String filename) {
        String safe = filename.replaceAll("[^A-Za-z0-9._+-]", "_");
        if (safe.isBlank()) {
            safe = "blob";
        }
        return tenantId + "/" + attachmentId + "/" + safe;
    }

    private static String sha256Hex(byte[] data) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(digest.digest(data));
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException(ex);
        }
    }

    public record LoadedAttachment(AttachmentEntity entity, byte[] data) {}
}

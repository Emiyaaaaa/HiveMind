package io.agentflow.api.service;

import io.agentflow.api.dto.AgentCreateRequest;
import io.agentflow.api.dto.AgentResponse;
import io.agentflow.api.dto.AgentUpdateRequest;
import io.agentflow.api.dto.AgentVersionDiffResponse;
import io.agentflow.api.dto.AgentVersionResponse;
import io.agentflow.api.entity.AgentEntity;
import io.agentflow.api.entity.AgentVersionEntity;
import io.agentflow.api.repository.AgentRepository;
import io.agentflow.api.repository.AgentVersionRepository;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.TreeSet;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AgentService {

    private final AgentRepository repository;
    private final AgentVersionRepository versionRepository;

    public AgentService(AgentRepository repository, AgentVersionRepository versionRepository) {
        this.repository = repository;
        this.versionRepository = versionRepository;
    }

    @Transactional
    public AgentResponse create(AgentCreateRequest req) {
        if (repository.existsByName(req.getName())) {
            throw new AgentNameConflictException(req.getName());
        }
        AgentEntity entity = new AgentEntity();
        entity.setName(req.getName());
        entity.setDescription(req.getDescription());
        entity.setAdapter(req.getAdapter());
        entity.setConfig(new HashMap<>(req.getConfig()));
        entity.setVersion(1);
        try {
            AgentEntity saved = repository.save(entity);
            versionRepository.save(snapshot(saved, "initial"));
            return AgentResponse.fromEntity(saved);
        } catch (DataIntegrityViolationException e) {
            throw new AgentNameConflictException(req.getName());
        }
    }

    @Transactional(readOnly = true)
    public List<AgentResponse> list() {
        return repository.findAllByOrderByCreatedAtDesc().stream()
                .map(AgentResponse::fromEntity)
                .toList();
    }

    @Transactional(readOnly = true)
    public AgentResponse get(String id) {
        return repository.findById(id)
                .map(AgentResponse::fromEntity)
                .orElseThrow(() -> new AgentNotFoundException(id));
    }

    @Transactional(readOnly = true)
    public AgentEntity getEntity(String id) {
        return repository.findById(id).orElseThrow(() -> new AgentNotFoundException(id));
    }

    @Transactional
    public AgentResponse update(String id, AgentUpdateRequest req) {
        AgentEntity agent = getEntity(id);

        if (req.isNameSet() && req.getName() != null) {
            agent.setName(req.getName());
        }

        String newDescription =
                req.isDescriptionSet() ? req.getDescription() : agent.getDescription();
        String newAdapter =
                req.isAdapterSet() && req.getAdapter() != null
                        ? req.getAdapter()
                        : agent.getAdapter();
        Map<String, Object> newConfig =
                req.isConfigSet() && req.getConfig() != null
                        ? new HashMap<>(req.getConfig())
                        : new HashMap<>(agent.getConfig());

        boolean bump =
                (req.isDescriptionSet() && !Objects.equals(newDescription, agent.getDescription()))
                        || (req.isAdapterSet() && !Objects.equals(newAdapter, agent.getAdapter()))
                        || (req.isConfigSet() && !Objects.equals(newConfig, agent.getConfig()));

        if (req.isDescriptionSet()) {
            agent.setDescription(req.getDescription());
        }
        if (req.isAdapterSet() && req.getAdapter() != null) {
            agent.setAdapter(req.getAdapter());
        }
        if (req.isConfigSet() && req.getConfig() != null) {
            agent.setConfig(new HashMap<>(req.getConfig()));
        }

        try {
            if (bump) {
                agent.setVersion(agent.getVersion() + 1);
                AgentEntity saved = repository.save(agent);
                versionRepository.save(snapshot(saved, req.getNote()));
                return AgentResponse.fromEntity(saved);
            }
            return AgentResponse.fromEntity(repository.save(agent));
        } catch (DataIntegrityViolationException e) {
            throw new AgentNameConflictException(
                    req.isNameSet() ? req.getName() : agent.getName());
        }
    }

    @Transactional(readOnly = true)
    public List<AgentVersionResponse> listVersions(String agentId) {
        getEntity(agentId);
        return versionRepository.findByAgentIdOrderByVersionDesc(agentId).stream()
                .map(AgentVersionResponse::fromEntity)
                .toList();
    }

    @Transactional(readOnly = true)
    public AgentVersionResponse getVersion(String agentId, int version) {
        getEntity(agentId);
        return versionRepository
                .findByAgentIdAndVersion(agentId, version)
                .map(AgentVersionResponse::fromEntity)
                .orElseThrow(() -> new AgentVersionNotFoundException(version));
    }

    @Transactional(readOnly = true)
    public AgentVersionDiffResponse diff(String agentId, int fromVersion, int toVersion) {
        getEntity(agentId);
        AgentVersionEntity left =
                versionRepository
                        .findByAgentIdAndVersion(agentId, fromVersion)
                        .orElseThrow(() -> new AgentVersionNotFoundException(fromVersion));
        AgentVersionEntity right =
                versionRepository
                        .findByAgentIdAndVersion(agentId, toVersion)
                        .orElseThrow(() -> new AgentVersionNotFoundException(toVersion));

        AgentVersionDiffResponse diff = new AgentVersionDiffResponse();
        diff.setFromVersion(fromVersion);
        diff.setToVersion(toVersion);
        if (!Objects.equals(left.getAdapter(), right.getAdapter())) {
            diff.setAdapter(Map.of("from", left.getAdapter(), "to", right.getAdapter()));
        }
        if (!Objects.equals(left.getDescription(), right.getDescription())) {
            Map<String, Object> description = new LinkedHashMap<>();
            description.put("from", left.getDescription());
            description.put("to", right.getDescription());
            diff.setDescription(description);
        }
        diff.setConfig(configDiff(left.getConfig(), right.getConfig()));
        return diff;
    }

    @Transactional
    public AgentResponse restore(String agentId, int version) {
        AgentEntity agent = getEntity(agentId);
        AgentVersionEntity snap =
                versionRepository
                        .findByAgentIdAndVersion(agentId, version)
                        .orElseThrow(() -> new AgentVersionNotFoundException(version));

        if (Objects.equals(agent.getAdapter(), snap.getAdapter())
                && Objects.equals(agent.getConfig(), snap.getConfig())
                && Objects.equals(agent.getDescription(), snap.getDescription())) {
            return AgentResponse.fromEntity(agent);
        }

        agent.setAdapter(snap.getAdapter());
        agent.setConfig(new HashMap<>(snap.getConfig()));
        agent.setDescription(snap.getDescription());
        agent.setVersion(agent.getVersion() + 1);
        AgentEntity saved = repository.save(agent);
        versionRepository.save(snapshot(saved, "restored from v" + version));
        return AgentResponse.fromEntity(saved);
    }

    private static AgentVersionEntity snapshot(AgentEntity agent, String note) {
        AgentVersionEntity row = new AgentVersionEntity();
        row.setAgentId(agent.getId());
        row.setVersion(agent.getVersion());
        row.setDescription(agent.getDescription());
        row.setAdapter(agent.getAdapter());
        row.setConfig(new HashMap<>(agent.getConfig()));
        row.setNote(note);
        return row;
    }

    @SuppressWarnings("unchecked")
    static Map<String, Object> configDiff(Map<String, Object> left, Map<String, Object> right) {
        Map<String, Object> added = new LinkedHashMap<>();
        Map<String, Object> removed = new LinkedHashMap<>();
        Map<String, Object> changed = new LinkedHashMap<>();
        walk(
                left == null ? Map.of() : left,
                right == null ? Map.of() : right,
                "",
                added,
                removed,
                changed);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("added", added);
        out.put("removed", removed);
        out.put("changed", changed);
        return out;
    }

    @SuppressWarnings("unchecked")
    private static void walk(
            Object left,
            Object right,
            String path,
            Map<String, Object> added,
            Map<String, Object> removed,
            Map<String, Object> changed) {
        if (left instanceof Map<?, ?> leftMap && right instanceof Map<?, ?> rightMap) {
            TreeSet<String> keys = new TreeSet<>();
            leftMap.keySet().forEach(k -> keys.add(String.valueOf(k)));
            rightMap.keySet().forEach(k -> keys.add(String.valueOf(k)));
            for (String key : keys) {
                String child = path.isEmpty() ? key : path + "." + key;
                boolean inLeft = leftMap.containsKey(key);
                boolean inRight = rightMap.containsKey(key);
                if (!inLeft) {
                    added.put(child, rightMap.get(key));
                } else if (!inRight) {
                    removed.put(child, leftMap.get(key));
                } else {
                    walk(leftMap.get(key), rightMap.get(key), child, added, removed, changed);
                }
            }
            return;
        }
        if (!Objects.equals(left, right)) {
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("from", left);
            entry.put("to", right);
            changed.put(path.isEmpty() ? "" : path, entry);
        }
    }
}

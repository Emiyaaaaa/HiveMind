package io.agentflow.api.service;

import io.agentflow.api.dto.AgentCreateRequest;
import io.agentflow.api.dto.AgentResponse;
import io.agentflow.api.entity.AgentEntity;
import io.agentflow.api.repository.AgentRepository;
import java.util.HashMap;
import java.util.List;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AgentService {

    private final AgentRepository repository;

    public AgentService(AgentRepository repository) {
        this.repository = repository;
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
        try {
            AgentEntity saved = repository.save(entity);
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
}

package io.agentflow.api.repository;

import io.agentflow.api.entity.RunEntity;
import java.util.List;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

public interface RunRepository extends JpaRepository<RunEntity, String> {

    @Query("SELECT r FROM RunEntity r ORDER BY r.createdAt DESC")
    List<RunEntity> findRecent(Pageable pageable);
}

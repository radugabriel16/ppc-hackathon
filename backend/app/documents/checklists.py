"""Use READY documents, not uploaded-but-failed files, to complete checklists."""
MISSING_CASES = """
    SELECT cc.id AS case_id, cc.client_id, cc.status AS case_status, c.external_code, c.region_id,
           covered_subregion(p.location,c.region_id) AS segment_id,
           ST_AsEWKT(p.location) AS location,
           jsonb_agg(jsonb_build_object('id',dt.id,'code',dt.code,'name',dt.name)
                     ORDER BY dt.code) AS missing_document_types
    FROM connection_cases cc JOIN clients c ON c.id=cc.client_id
    JOIN regions r ON r.id=c.region_id
    CROSS JOIN LATERAL (
        SELECT coalesce(c.location,
            (SELECT location FROM meters WHERE client_id=c.id AND location IS NOT NULL
             AND ST_Covers(r.geometry,location)
             ORDER BY external_code LIMIT 1), ST_PointOnSurface(r.geometry)) AS location
    ) p
    CROSS JOIN document_types dt
    WHERE dt.required_for_connection
      AND NOT EXISTS (
          SELECT 1 FROM client_documents cd JOIN files f ON f.id=cd.file_id
          WHERE cd.case_id=cc.id AND cd.document_type_id=dt.id AND f.status='READY' AND cd.superseded_at IS NULL
      )
    GROUP BY cc.id,c.id,p.location
"""

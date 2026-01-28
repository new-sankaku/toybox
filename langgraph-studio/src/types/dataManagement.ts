export interface BackupEntry{
 name:string
 size:number
 createdAt:string
}

export interface ArchiveEntry{
 name:string
 size:number
 createdAt:string
}

export interface ArchiveStats{
 totalArchives:number
 totalSize:number
 oldestArchive:string|null
 newestArchive:string|null
}

export interface CleanupEstimate{
 tracesCount:number
 estimatedSize:number
}

export interface RecoveryStatus{
 interruptedAgents:number
 interruptedProjects:number
}

export interface SystemStats{
 backups:{count:number;totalSize:number}
 archives:ArchiveStats
 rateLimiter:{activeKeys:number}
}

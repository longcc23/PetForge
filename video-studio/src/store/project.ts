import type { Storyboard } from '@/types'

const PROJECTS_KEY = 'petmovie-projects'
const CURRENT_PROJECT_KEY = 'petmovie-current-project-id'

export interface ProjectData {
  id: string
  name: string
  actorImage: string | null
  actorName: string
  sceneDescription: string
  openingImage: string | null
  storyboards: Storyboard[]
  finalVideoUrl: string | null
  status: 'draft' | 'generating_opening' | 'editing_storyboard' | 'generating_video' | 'completed'
  createdAt: number
  updatedAt: number
}

// Helper to estimate size of a string in bytes
function estimateSize(str: string | null): number {
  if (!str) return 0
  // Base64 is roughly 4/3 of original size, but we'll use UTF-16 length as approximation
  return str.length * 2  // UTF-16 encoding
}

// Maximum size for localStorage (conservative: 4MB)
const MAX_STORAGE_SIZE = 4 * 1024 * 1024  // 4MB

export function saveProject(data: Partial<ProjectData>, projectId?: string): string {
  const id = projectId || getCurrentProjectId() || generateProjectId()
  const existing = projectId ? getProjectById(id) : getProject()
  
  let project: ProjectData = {
    id,
    name: data.name ?? existing?.name ?? `项目 ${new Date().toLocaleDateString()}`,
    actorImage: data.actorImage ?? existing?.actorImage ?? null,
    actorName: data.actorName ?? existing?.actorName ?? '',
    sceneDescription: data.sceneDescription ?? existing?.sceneDescription ?? '',
    openingImage: data.openingImage ?? existing?.openingImage ?? null,
    storyboards: data.storyboards ?? existing?.storyboards ?? [],
    finalVideoUrl: data.finalVideoUrl ?? existing?.finalVideoUrl ?? null,
    status: data.status ?? existing?.status ?? 'draft',
    createdAt: existing?.createdAt ?? Date.now(),
    updatedAt: Date.now()
  }
  
  // Estimate total size
  const projectJson = JSON.stringify(project)
  const estimatedSize = estimateSize(projectJson)
  
  // If too large, handle gracefully
  if (estimatedSize > MAX_STORAGE_SIZE) {
    console.warn('Project data too large, optimizing storage...')
    
    // ⚠️ 不再删除开场图和演员图的 URL（它们应该是短路径，不是 base64）
    // 只删除 base64 格式的大型数据（如果有的话）
    
    // Remove video if it's base64 (very large)
    if (project.finalVideoUrl && project.finalVideoUrl.startsWith('data:video')) {
      console.warn('Removing video base64 to save space')
      project.finalVideoUrl = null
    }
    
    // Remove any storyboard base64 images (shouldn't exist, but just in case)
    project.storyboards = project.storyboards.map(sb => {
      const optimized = { ...sb }
      
      // 如果视频 URL 是 base64，移除
      if (optimized.videoUrl && optimized.videoUrl.startsWith('data:video')) {
        optimized.videoUrl = undefined
      }
      
      // 帧 URL 应该是路径，保留
      return optimized
    })
    
    // Re-check size after optimization
    const reducedJson = JSON.stringify(project)
    const reducedSize = estimateSize(reducedJson)
    
    if (reducedSize > MAX_STORAGE_SIZE) {
      // 如果还是太大，只移除视频段落的视频 URL（保留帧 URL 用于链接）
      console.warn('Still too large, removing video URLs but keeping frame URLs')
      project.storyboards = project.storyboards.map(sb => ({
        ...sb,
        videoUrl: undefined  // 移除视频 URL
        // 保留 firstFrameUrl 和 lastFrameUrl 用于帧链接
      }))
    }
  }
  
  try {
    const projects = getAllProjects()
    const index = projects.findIndex(p => p.id === id)
    if (index >= 0) {
      projects[index] = project
    } else {
      projects.push(project)
    }
    localStorage.setItem(PROJECTS_KEY, JSON.stringify(projects))
    setCurrentProjectId(id)
    return id
  } catch (error) {
    // Handle quota exceeded error
    if (error instanceof DOMException && error.name === 'QuotaExceededError') {
      console.warn('localStorage quota exceeded even after optimization')
      
      // Last resort: save only essential data (no images/videos)
      const minimalProject: ProjectData = {
        id: project.id,
        name: project.name,
        actorImage: null,
        actorName: project.actorName,
        sceneDescription: project.sceneDescription,
        openingImage: null,
        storyboards: project.storyboards.map(sb => ({
          ...sb,
          videoUrl: undefined,
          firstFrameUrl: undefined,
          lastFrameUrl: undefined
        })),
        finalVideoUrl: null,
        status: project.status,
        createdAt: project.createdAt,
        updatedAt: project.updatedAt
      }
      
      try {
        const projects = getAllProjects()
        const index = projects.findIndex(p => p.id === id)
        if (index >= 0) {
          projects[index] = minimalProject
        } else {
          projects.push(minimalProject)
        }
        localStorage.setItem(PROJECTS_KEY, JSON.stringify(projects))
        console.warn('Saved minimal project data (images/videos removed)')
        return id
      } catch (e) {
        console.error('Failed to save even minimal project data', e)
        return id
      }
    } else {
      throw error
    }
  }
}

export function getProject(): ProjectData | null {
  const currentId = getCurrentProjectId()
  if (!currentId) return null
  return getProjectById(currentId)
}

export function getProjectById(id: string): ProjectData | null {
  const projects = getAllProjects()
  return projects.find(p => p.id === id) || null
}

export function getAllProjects(): ProjectData[] {
  const stored = localStorage.getItem(PROJECTS_KEY)
  if (!stored) return []
  try {
    return JSON.parse(stored)
  } catch {
    return []
  }
}

function generateProjectId(): string {
  return `project_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
}

export function getCurrentProjectId(): string | null {
  return localStorage.getItem(CURRENT_PROJECT_KEY)
}

export function setCurrentProjectId(id: string): void {
  localStorage.setItem(CURRENT_PROJECT_KEY, id)
}

export function createNewProject(name?: string): string {
  const id = generateProjectId()
  const project: ProjectData = {
    id,
    name: name || `项目 ${new Date().toLocaleDateString()}`,
    actorImage: null,
    actorName: '',
    sceneDescription: '',
    openingImage: null,
    storyboards: [],
    finalVideoUrl: null,
    status: 'draft',
    createdAt: Date.now(),
    updatedAt: Date.now()
  }
  const projects = getAllProjects()
  projects.push(project)
  localStorage.setItem(PROJECTS_KEY, JSON.stringify(projects))
  setCurrentProjectId(id)
  return id
}

export function deleteProject(id: string): void {
  const projects = getAllProjects()
  const filtered = projects.filter(p => p.id !== id)
  localStorage.setItem(PROJECTS_KEY, JSON.stringify(filtered))
  if (getCurrentProjectId() === id) {
    localStorage.removeItem(CURRENT_PROJECT_KEY)
  }
}

export function clearCurrentProject(): void {
  localStorage.removeItem(CURRENT_PROJECT_KEY)
}

export function hasProject(): boolean {
  const project = getProject()
  return project !== null && (project.openingImage !== null || project.storyboards.length > 0)
}

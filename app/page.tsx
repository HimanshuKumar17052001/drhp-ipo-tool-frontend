"use client"

import type React from "react"
import { useState, useRef, useCallback, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter, DialogClose } from "@/components/ui/dialog"
import { Badge } from "@/components/ui/badge"
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import {
  Upload,
  FileText,
  Download,
  Building2,
  Trash2,
  Play,
  X,
  AlertCircle,
  Loader2,
  Users,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Eye,
} from "lucide-react"

// --- API Configuration ---
const API_BASE_URL = "https://drhp-note-generation.onrender.com"

// --- Type Definitions ---
interface Company {
  id: string
  name: string
  corporate_identity_number: string
  website_link?: string
  created_at: string
  processing_status: "PENDING" | "PROCESSING" | "COMPLETED" | "FAILED"
  has_markdown: boolean
  pages_count: number
  checklist_outputs_count: number
}

interface ProcessingStatus {
  step: string
  message: string
  status: string
  progress?: number // Optional progress percentage
}

type LeftPaneState = "upload" | "loading" | "preview"

export default function DRHPIPOTool() {
  // --- State Management ---
  const [uploadedFile, setUploadedFile] = useState<File | null>(null)
  const [pdfPreviewUrl, setPdfPreviewUrl] = useState<string>("")
  const [leftPaneState, setLeftPaneState] = useState<LeftPaneState>("upload")
  const [isProcessing, setIsProcessing] = useState(false)
  const [processingStatus, setProcessingStatus] = useState<ProcessingStatus | null>(null)
  const [generatedMarkdown, setGeneratedMarkdown] = useState<string>("")
  const [companies, setCompanies] = useState<Company[]>([])
  const [isLoadingCompanies, setIsLoadingCompanies] = useState(true)

  // Modal/Dialog States
  const [showCompanyDetail, setShowCompanyDetail] = useState(false)
  const [selectedCompanyDetail, setSelectedCompanyDetail] = useState<Company | null>(null)
  const [companyReportMarkdown, setCompanyReportMarkdown] = useState<string>("")
  const [isLoadingCompanyReport, setIsLoadingCompanyReport] = useState(false)
  const [generatedPdfBlobUrl, setGeneratedPdfBlobUrl] = useState<string>("")
  const [companyReportPdfBlobUrl, setCompanyReportPdfBlobUrl] = useState<string>("")

  // Confirmation/Warning Dialogs
  const [showGenerateConfirm, setShowGenerateConfirm] = useState(false)
  const [showRemoveConfirm, setShowRemoveConfirm] = useState(false)
  const [showWarning, setShowWarning] = useState<string>("")

  // UI Interaction States
  const fileInputRef = useRef<HTMLInputElement>(null)
  const companyLogoInputRef = useRef<HTMLInputElement>(null)
  const entityLogoInputRef = useRef<HTMLInputElement>(null)
  const [isDragOver, setIsDragOver] = useState(false)

  // PDF Viewer states
  const [currentPage, setCurrentPage] = useState<number>(1)
  const [totalPages, setTotalPages] = useState<number>(0)
  const [scale, setScale] = useState<number>(1.0)
  const [rotation, setRotation] = useState<number>(0)

  // --- API Communication ---

  const fetchCompanies = useCallback(async () => {
    setIsLoadingCompanies(true)
    try {
      const response = await fetch(`${API_BASE_URL}/companies/`)
      if (!response.ok) {
        throw new Error("Failed to fetch companies.")
      }
      const data: Company[] = await response.json()
      setCompanies(data)
    } catch (error) {
      console.error(error)
      setShowWarning("Could not load the list of companies. Please refresh the page.")
    } finally {
      setIsLoadingCompanies(false)
    }
  }, [])

  useEffect(() => {
    fetchCompanies()
  }, [fetchCompanies])

  const generatePdfFromMarkdown = async (markdown: string, companyName: string): Promise<string | null> => {
    try {
      const response = await fetch(`${API_BASE_URL}/reports/generate-pdf`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          markdown_content: markdown,
          company_name: companyName,
        }),
      })
      if (!response.ok) {
        throw new Error(`PDF generation failed with status: ${response.status}`)
      }
      const blob = await response.blob()
      return URL.createObjectURL(blob)
    } catch (error) {
      console.error("Error generating PDF from markdown:", error)
      setShowWarning("Failed to generate the PDF report from the processed notes.")
      return null
    }
  }

  const processStream = async (
    response: Response,
    onUpdate: (data: any) => void,
    onComplete: (data: any) => void,
    onError: (message: string) => void,
  ) => {
    const reader = response.body?.getReader()
    if (!reader) {
      onError("Failed to read response stream.")
      return
    }
    const decoder = new TextDecoder()
    let buffer = ""

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split("\n\n")
      buffer = lines.pop() || ""

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const data = JSON.parse(line.substring(6))
            if (data.status === "COMPLETED") {
              onComplete(data)
            } else if (data.status === "FAILED") {
              onError(data.message)
            } else {
              onUpdate(data)
            }
          } catch (e) {
            console.error("Failed to parse SSE message:", line, e)
          }
        }
      }
    }
  }

  const confirmGenerate = async () => {
    if (!uploadedFile) return
    setShowGenerateConfirm(false)
    setIsProcessing(true)
    setProcessingStatus({ step: "uploading", message: "Uploading file...", status: "PROCESSING" })
    setGeneratedMarkdown("")
    setGeneratedPdfBlobUrl("")

    const formData = new FormData()
    formData.append("file", uploadedFile)

    try {
      const response = await fetch(`${API_BASE_URL}/companies/`, {
        method: "POST",
        body: formData,
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || `Upload failed with status: ${response.status}`)
      }

      await processStream(
        response,
        (update) => setProcessingStatus(update),
        async (finalData) => {
          setProcessingStatus({ step: "generating_pdf", message: "Generating PDF report...", status: "PROCESSING" })
          setGeneratedMarkdown(finalData.markdown)
          const pdfUrl = await generatePdfFromMarkdown(finalData.markdown, uploadedFile.name.replace(".pdf", ""))
          if (pdfUrl) {
            setGeneratedPdfBlobUrl(pdfUrl)
          }
          setIsProcessing(false)
          setProcessingStatus(null)
          fetchCompanies() // Refresh company list
        },
        (errorMessage) => {
          setShowWarning(`Processing failed: ${errorMessage}`)
          setIsProcessing(false)
          setProcessingStatus(null)
        },
      )
    } catch (error) {
      console.error("File upload/processing error:", error)
      setShowWarning(`An error occurred: ${error instanceof Error ? error.message : String(error)}`)
      setIsProcessing(false)
      setProcessingStatus(null)
    }
  }

  const handleRegenerateReport = async () => {
    if (!selectedCompanyDetail) return
    setIsLoadingCompanyReport(true)
    setCompanyReportPdfBlobUrl("")

    try {
      const response = await fetch(`${API_BASE_URL}/companies/${selectedCompanyDetail.id}/regenerate`, {
        method: "POST",
      })

      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || `Regeneration failed with status: ${response.status}`)
      }

      await processStream(
        response,
        (update) => {
          console.log("Regeneration progress:", update)
        },
        async (finalData) => {
          setCompanyReportMarkdown(finalData.markdown)
          const pdfUrl = await generatePdfFromMarkdown(finalData.markdown, selectedCompanyDetail.name)
          if (pdfUrl) {
            setCompanyReportPdfBlobUrl(pdfUrl)
          }
          setIsLoadingCompanyReport(false)
          fetchCompanies()
        },
        (errorMessage) => {
          setShowWarning(`Regeneration failed: ${errorMessage}`)
          setIsLoadingCompanyReport(false)
        },
      )
    } catch (error) {
      console.error("Regeneration error:", error)
      setShowWarning(`An error occurred during regeneration: ${error instanceof Error ? error.message : String(error)}`)
      setIsLoadingCompanyReport(false)
    }
  }

  const handleCompanySelect = async (company: Company) => {
    if (company.processing_status !== "COMPLETED") return

    setSelectedCompanyDetail(company)
    setShowCompanyDetail(true)
    setCompanyReportPdfBlobUrl("")
    setIsLoadingCompanyReport(true)

    try {
      const response = await fetch(`${API_BASE_URL}/companies/${company.id}/report`)
      if (!response.ok) {
        throw new Error("Failed to fetch company report.")
      }
      const data = await response.json()
      setCompanyReportMarkdown(data.markdown)

      const pdfUrl = await generatePdfFromMarkdown(data.markdown, company.name)
      if (pdfUrl) {
        setCompanyReportPdfBlobUrl(pdfUrl)
      }
    } catch (error) {
      console.error(error)
      setShowWarning("Could not load the company report.")
    } finally {
      setIsLoadingCompanyReport(false)
    }
  }

  const handleDeleteCompany = async () => {
    if (!selectedCompanyDetail) return
    try {
      const response = await fetch(`${API_BASE_URL}/companies/${selectedCompanyDetail.id}`, {
        method: "DELETE",
      })
      if (!response.ok) {
        throw new Error("Failed to delete company.")
      }
      setCompanies((prev) => prev.filter((c) => c.id !== selectedCompanyDetail.id))
      setShowCompanyDetail(false)
      setSelectedCompanyDetail(null)
    } catch (error) {
      console.error(error)
      setShowWarning("Failed to delete the company.")
    }
  }

  const handleLogoUpload = async (file: File) => {
    if (!file) return
    const formData = new FormData()
    formData.append("file", file)

    try {
      const response = await fetch(`${API_BASE_URL}/assets/logos`, {
        method: "POST",
        body: formData,
      })
      if (!response.ok) {
        const errorData = await response.json()
        throw new Error(errorData.detail || "Logo upload failed")
      }
      const result = await response.json()
      setShowWarning(`Logo "${result.filename}" uploaded successfully! ID: ${result.logo_id}`)
      // Here you would typically associate this logo_id with a company or entity config
    } catch (error) {
      console.error("Logo upload error:", error)
      setShowWarning(`Logo upload failed: ${error instanceof Error ? error.message : "Unknown error"}`)
    }
  }

  // --- UI Handlers ---

  const handleFileUpload = (file: File) => {
    if (file.type !== "application/pdf") {
      setShowWarning("Please upload a PDF file only.")
      return
    }
    setLeftPaneState("loading")
    setUploadedFile(file)
    const url = URL.createObjectURL(file)
    setPdfPreviewUrl(url)
    setLeftPaneState("preview")
    setGeneratedMarkdown("")
    setGeneratedPdfBlobUrl("")
    setProcessingStatus(null)
    setCurrentPage(1)
    setTotalPages(0)
    setScale(1.0)
    setRotation(0)
  }

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) {
      handleFileUpload(files[0])
    }
  }, [])

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
  }, [])

  const handleGenerateIPO = () => {
    if (!uploadedFile) {
      setShowWarning("Please upload a DRHP PDF file first.")
      return
    }
    setShowGenerateConfirm(true)
  }

  const handleRemovePDF = () => {
    setShowRemoveConfirm(true)
  }

  const confirmRemove = () => {
    setUploadedFile(null)
    if (pdfPreviewUrl) URL.revokeObjectURL(pdfPreviewUrl)
    setPdfPreviewUrl("")
    setLeftPaneState("upload")
    setGeneratedMarkdown("")
    if (generatedPdfBlobUrl) URL.revokeObjectURL(generatedPdfBlobUrl)
    setGeneratedPdfBlobUrl("")
    setProcessingStatus(null)
    setShowRemoveConfirm(false)
  }

  const downloadPDF = (blobUrl: string, filename: string) => {
    if (!blobUrl) {
      setShowWarning("No PDF is available to download.")
      return
    }
    const a = document.createElement("a")
    a.href = blobUrl
    a.download = filename
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  // --- Render Logic ---

  const renderLeftPane = () => {
    switch (leftPaneState) {
      case "upload":
        return (
          <div className="h-full flex flex-col p-6">
            <div className="text-center mb-4 shrink-0">
              <h2 className="text-[#023047] text-xl font-bold drop-shadow-sm">DRHP Document Upload</h2>
              <p className="text-gray-500 text-sm mt-1">Upload your DRHP PDF document to get started</p>
            </div>

            <div
              className={`border-dashed flex-grow text-center transition-all duration-300 depth-upload cursor-pointer rounded-xl border-2 flex flex-col items-center justify-center ${
                isDragOver
                  ? "border-[#FFB703] bg-[#FFB703]/10 scale-[1.02]"
                  : "border-gray-300 hover:border-[#219EBC] hover:bg-[#219EBC]/5"
              }`}
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onClick={() => fileInputRef.current?.click()}
            >
              <Upload className="w-16 h-16 mb-4 text-gray-400" />
              <h3 className="font-semibold text-lg text-gray-700">Drop DRHP PDF here</h3>
              <p className="text-sm text-gray-400 italic my-2">or click to browse files</p>
              <Button
                variant="outline"
                size="lg"
                className="border-[#219EBC] text-[#219EBC] hover:bg-[#219EBC] hover:text-white bg-transparent depth-button px-10 py-2 text-base mt-4"
              >
                Browse Files
              </Button>
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0]
                  if (file) handleFileUpload(file)
                }}
              />
            </div>
          </div>
        )

      case "loading":
        return (
          <div className="h-full flex items-center justify-center">
            <div className="text-center">
              <div className="relative mb-8">
                <div className="w-24 h-24 border-4 border-[#219EBC]/20 rounded-full animate-spin border-t-[#219EBC] mx-auto"></div>
                <FileText className="w-10 h-10 absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 text-[#219EBC]" />
              </div>
              <h3 className="text-2xl font-semibold mb-3 text-[#023047]">Preparing Preview...</h3>
              <p className="text-gray-600 text-lg">Please wait while we prepare your PDF for viewing</p>
            </div>
          </div>
        )

      case "preview":
        return (
          <div className="h-full flex flex-col">
            <div className="p-2 border-b bg-gradient-to-r from-[#5CAE6]/10 to-[#219EBC]/10 flex items-center justify-between flex-wrap gap-2">
              <div className="flex items-center space-x-2">
                <div className="flex items-center space-x-1 bg-white rounded-lg p-1 depth-button">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                    disabled={currentPage <= 1}
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </Button>
                  <span className="px-2 text-sm font-medium">
                    {currentPage} / {totalPages || "..."}
                  </span>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                    disabled={currentPage >= totalPages}
                  >
                    <ChevronRight className="w-4 h-4" />
                  </Button>
                </div>
              </div>

              <div className="flex items-center space-x-2">
                <Button variant="destructive" size="sm" onClick={handleRemovePDF} className="depth-button">
                  <Trash2 className="w-3 h-3 mr-1" />
                  Remove
                </Button>
                <Button
                  onClick={handleGenerateIPO}
                  disabled={isProcessing}
                  size="sm"
                  className="bg-gradient-to-r from-[#FFB703] to-[#FB8500] hover:from-[#FB8500] hover:to-[#FFB703] text-white depth-button glow-orange"
                >
                  {isProcessing ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Play className="w-3 h-3 mr-1" />}
                  Generate IPO Notes
                </Button>
              </div>
            </div>

            <div className="flex-1 overflow-auto bg-gray-100 p-2">
              <div className="flex justify-center">
                <div className="depth-content bg-white rounded-lg shadow-lg w-full max-w-4xl">
                  {pdfPreviewUrl ? (
                    <div
                      className="w-full h-full min-h-[600px] rounded-lg overflow-hidden"
                      style={{
                        transform: `scale(${scale}) rotate(${rotation}deg)`,
                        transformOrigin: "center center",
                        transition: "transform 0.2s ease",
                      }}
                    >
                      <iframe
                        src={`${pdfPreviewUrl}#page=${currentPage}&zoom=${Math.round(scale * 100)}`}
                        className="w-full h-full border-0 rounded-lg"
                        title="PDF Preview"
                        style={{ minHeight: "calc(100vh - 200px)" }}
                      />
                    </div>
                  ) : (
                    <div className="flex items-center justify-center p-8 min-h-[600px]">
                      <div className="text-center text-gray-500">
                        <Eye className="w-12 h-12 mx-auto mb-3" />
                        <h3 className="text-lg font-medium mb-2">PDF Preview</h3>
                        <p className="text-sm">Your PDF document will appear here</p>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>
        )

      default:
        return null
    }
  }

  return (
    <div className="min-h-screen enhanced-bg">
      <nav className="bg-gradient-to-r from-[#219EBC] to-[#023047] px-4 py-2 depth-nav float-animation">
        <div className="flex items-center justify-between">
          <div className="flex items-center">
            <h1 className="text-lg font-semibold text-white drop-shadow-lg">DRHP IPO Notes Generator</h1>
          </div>

          <div className="flex items-center space-x-2">
            <Button
              variant="outline"
              size="sm"
              className="bg-white/10 hover:bg-white/20 text-white border-white/20 depth-button glow-blue"
              onClick={() => companyLogoInputRef.current?.click()}
            >
              <Upload className="w-4 h-4 mr-1" />
              Upload Company Logo
            </Button>
            <input
              type="file"
              ref={companyLogoInputRef}
              className="hidden"
              accept="image/*"
              onChange={(e) => e.target.files && handleLogoUpload(e.target.files[0])}
            />
            <Button
              variant="outline"
              size="sm"
              className="bg-white/10 hover:bg-white/20 text-white border-white/20 depth-button glow-blue"
              onClick={() => entityLogoInputRef.current?.click()}
            >
              <Building2 className="w-4 h-4 mr-1" />
              Upload Entity Logo
            </Button>
            <input
              type="file"
              ref={entityLogoInputRef}
              className="hidden"
              accept="image/*"
              onChange={(e) => e.target.files && handleLogoUpload(e.target.files[0])}
            />

            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className="bg-white/10 hover:bg-white/20 text-white border-white/20 depth-button glow-blue"
                  disabled={isLoadingCompanies}
                >
                  {isLoadingCompanies ? (
                    <Loader2 className="w-4 h-4 mr-1 animate-spin" />
                  ) : (
                    <Users className="w-4 h-4 mr-1" />
                  )}
                  View Companies
                  <ChevronDown className="w-4 h-4 ml-1" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent className="w-80 max-h-96 overflow-auto depth-dropdown">
                {companies.length > 0 ? (
                  companies.map((company) => (
                    <DropdownMenuItem
                      key={company.id}
                      className={`flex flex-col items-start p-3 shimmer-effect ${
                        company.processing_status !== "COMPLETED"
                          ? "cursor-not-allowed opacity-50"
                          : "cursor-pointer hover:bg-gray-50"
                      }`}
                      onClick={() => handleCompanySelect(company)}
                      disabled={company.processing_status !== "COMPLETED"}
                    >
                      <div className="w-full">
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-medium text-sm">{company.name}</span>
                          <Badge
                            variant="outline"
                            className={`text-xs depth-badge ${
                              company.processing_status === "COMPLETED"
                                ? "bg-green-50 text-green-700 border-green-200"
                                : company.processing_status === "PROCESSING"
                                  ? "bg-blue-50 text-blue-700 border-blue-200"
                                  : "bg-red-50 text-red-700 border-red-200"
                            }`}
                          >
                            {company.processing_status}
                          </Badge>
                        </div>
                        <div className="text-xs text-gray-500 space-y-1">
                          <div>CIN: {company.corporate_identity_number}</div>
                          <div>Uploaded: {new Date(company.created_at).toLocaleDateString()}</div>
                        </div>
                      </div>
                    </DropdownMenuItem>
                  ))
                ) : (
                  <DropdownMenuItem disabled className="text-center justify-center p-3">
                    No companies found.
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>

            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                downloadPDF(generatedPdfBlobUrl, `${uploadedFile?.name.replace(".pdf", "") || "Report"}_IPO_Notes.pdf`)
              }
              disabled={!generatedPdfBlobUrl}
              className="bg-white/10 hover:bg-white/20 text-white border-white/20 depth-button glow-blue"
            >
              <Download className="w-4 h-4 mr-1" />
              Download as PDF
            </Button>
          </div>
        </div>
      </nav>

      <div className="flex h-[calc(100vh-52px)]">
        <div className="w-1/2 border-r border-gray-200 p-1">
          <Card className="h-full border-0 depth-card shimmer-effect">{renderLeftPane()}</Card>
        </div>

        <div className="w-1/2 p-1">
          <Card className="h-full flex flex-col border-0 depth-card shimmer-effect">
            <div className="p-3 border-b bg-gradient-to-r from-[#023047]/10 to-[#219EBC]/10 rounded-t-md">
              <h2 className="text-base font-medium text-[#023047] drop-shadow-sm">Generated IPO Notes</h2>
            </div>

            {isProcessing && processingStatus && (
              <div className="p-4 space-y-2 depth-status border-b border-gray-200 bg-white/50">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium">{processingStatus.message}</span>
                </div>
                {processingStatus.progress !== undefined && (
                  <Progress value={processingStatus.progress} className="h-1 enhanced-progress" />
                )}
              </div>
            )}

            <div className="flex-1 p-3 overflow-auto">
              {!generatedPdfBlobUrl && !isProcessing ? (
                <div className="h-full flex items-center justify-center">
                  <div className="text-center text-gray-500">
                    <FileText className="w-12 h-12 mx-auto mb-3" />
                    <h3 className="text-base font-medium mb-2">No IPO Generated</h3>
                    <p className="text-sm">Upload a DRHP PDF and generate IPO notes to view them here</p>
                  </div>
                </div>
              ) : isProcessing ? (
                <div className="h-full flex items-center justify-center">
                  <div className="text-center">
                    <div className="relative mb-6">
                      <div className="w-16 h-16 border-4 border-[#FFB703]/20 rounded-full animate-spin border-t-[#FFB703] mx-auto"></div>
                      <FileText className="w-6 h-6 absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 text-[#FFB703]" />
                    </div>
                    <h3 className="text-lg font-semibold mb-2 text-[#023047]">Generating IPO Notes...</h3>
                    <p className="text-gray-600 text-sm mb-2">Please have patience, this may take several minutes.</p>
                    {processingStatus && <p className="text-xs text-gray-500">{processingStatus.message}</p>}
                  </div>
                </div>
              ) : (
                <div className="prose prose-sm max-w-none h-full">
                  <div className="bg-white p-4 rounded-lg border depth-content h-full">
                    {generatedPdfBlobUrl ? (
                      <iframe
                        src={generatedPdfBlobUrl}
                        className="w-full h-full border-0 rounded-lg"
                        title="Generated IPO Notes PDF"
                      />
                    ) : (
                      <div className="flex items-center justify-center p-8 min-h-[600px]">
                        <div className="text-center text-gray-500">
                          <Eye className="w-12 h-12 mx-auto mb-3" />
                          <h3 className="text-lg font-medium mb-2">PDF Report Preview</h3>
                          <p className="text-sm">Your generated PDF report will appear here</p>
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </Card>
        </div>
      </div>

      {/* Dialogs */}
      <Dialog open={showGenerateConfirm} onOpenChange={setShowGenerateConfirm}>
        <DialogContent className="depth-dialog">
          <DialogHeader>
            <DialogTitle>Generate IPO Notes</DialogTitle>
          </DialogHeader>
          <p>Do you want to continue with generating IPO notes for this DRHP document?</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowGenerateConfirm(false)} className="depth-button">
              Cancel
            </Button>
            <Button
              onClick={confirmGenerate}
              className="bg-[#FFB703] hover:bg-[#FB8500] text-white depth-button glow-orange"
            >
              Continue
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showRemoveConfirm} onOpenChange={setShowRemoveConfirm}>
        <DialogContent className="depth-dialog">
          <DialogHeader>
            <DialogTitle>Remove PDF</DialogTitle>
          </DialogHeader>
          <p>Are you sure you want to remove the uploaded PDF? This will also clear any generated IPO notes.</p>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowRemoveConfirm(false)} className="depth-button">
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmRemove} className="depth-button">
              Remove
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!showWarning} onOpenChange={() => setShowWarning("")}>
        <DialogContent className="depth-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center space-x-2">
              <AlertCircle className="w-5 h-5 text-amber-500" />
              <span>Warning</span>
            </DialogTitle>
          </DialogHeader>
          <p>{showWarning}</p>
          <DialogFooter>
            <Button onClick={() => setShowWarning("")} className="depth-button">
              OK
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={showCompanyDetail} onOpenChange={setShowCompanyDetail}>
        <DialogContent
          onCloseAutoFocus={(e) => e.preventDefault()}
          className="w-screen h-screen max-w-full max-h-full rounded-none border-0 depth-dialog flex flex-col"
        >
          <DialogHeader className="border-b pb-4">
            <div className="flex items-center justify-between">
              <div>
                <DialogTitle className="text-xl font-bold">{selectedCompanyDetail?.name}</DialogTitle>
                <div className="flex items-center space-x-4 mt-2 text-sm text-gray-600">
                  <span>CIN: {selectedCompanyDetail?.corporate_identity_number}</span>
                  <span>
                    Uploaded:{" "}
                    {selectedCompanyDetail ? new Date(selectedCompanyDetail.created_at).toLocaleDateString() : ""}
                  </span>
                  <Badge
                    variant="outline"
                    className={`text-xs ${
                      selectedCompanyDetail?.processing_status === "COMPLETED"
                        ? "bg-green-50 text-green-700 border-green-200"
                        : "bg-blue-50 text-blue-700 border-blue-200"
                    }`}
                  >
                    {selectedCompanyDetail?.processing_status}
                  </Badge>
                </div>
              </div>
              <div className="flex items-center space-x-2">
                <Button
                  onClick={handleRegenerateReport}
                  disabled={isLoadingCompanyReport}
                  size="sm"
                  className="bg-gradient-to-r from-[#219EBC] to-[#023047] hover:from-[#023047] hover:to-[#219EBC] text-white depth-button"
                >
                  {isLoadingCompanyReport ? (
                    <Loader2 className="w-3 h-3 mr-1 animate-spin" />
                  ) : (
                    <Play className="w-3 h-3 mr-1" />
                  )}
                  Re-Generate IPO Note
                </Button>
                <Button
                  onClick={() =>
                    downloadPDF(
                      companyReportPdfBlobUrl,
                      `${selectedCompanyDetail?.name.replace(/ /g, "_") || "Report"}_IPO_Notes.pdf`,
                    )
                  }
                  disabled={!companyReportPdfBlobUrl}
                  size="sm"
                  className="bg-gradient-to-r from-green-500 to-green-600 text-white depth-button"
                >
                  <Download className="w-3 h-3 mr-1" />
                  Download PDF
                </Button>
                <Button onClick={handleDeleteCompany} variant="destructive" size="sm" className="depth-button">
                  <Trash2 className="w-3 h-3 mr-1" />
                  Delete Company
                </Button>
                <DialogClose asChild>
                  <Button variant="ghost" size="icon" className="rounded-full">
                    <X className="h-4 w-4" />
                  </Button>
                </DialogClose>
              </div>
            </div>
          </DialogHeader>

          <div className="flex-1 overflow-auto mt-4">
            {isLoadingCompanyReport ? (
              <div className="h-full flex items-center justify-center">
                <div className="text-center">
                  <Loader2 className="w-10 h-10 mx-auto mb-3 animate-spin text-[#219EBC]" />
                  <h3 className="text-base font-medium mb-2">Loading Report...</h3>
                  <p className="text-gray-500 text-sm">Please wait while the report is being generated.</p>
                </div>
              </div>
            ) : companyReportPdfBlobUrl ? (
              <div className="prose prose-sm max-w-none h-full">
                <div className="bg-white p-6 rounded-lg border depth-content h-full">
                  <iframe
                    src={companyReportPdfBlobUrl}
                    className="w-full h-full border-0 rounded-lg"
                    title="Company Report PDF"
                  />
                </div>
              </div>
            ) : (
              <div className="h-full flex items-center justify-center">
                <div className="text-center text-gray-500">
                  <FileText className="w-12 h-12 mx-auto mb-3" />
                  <h3 className="text-base font-medium mb-2">No Report Available</h3>
                  <p className="text-sm">This company doesn't have a generated report yet.</p>
                </div>
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

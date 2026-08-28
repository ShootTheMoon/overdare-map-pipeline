--!strict
-- Aligns the currently imported official Gyeonghoeru FBX batches to the palace map.
-- Only the exact unprocessed batch names below are touched, making reruns idempotent.

local BatchNormalizer = {}

local TARGET_OFFSET = Vector3.new(-33.68693923950195, 0, -8794.7626953125)

local function GetNormalizedName(name: string): string?
	if name == "GY_Gyeonghoeru_Batch_02_28962poly" then
		return "GY_Gyeonghoeru_Batch_02"
	elseif name == "GY_Gyeonghoeru_Batch_04_27400poly" then
		return "GY_Gyeonghoeru_Batch_04"
	elseif name == "GY_Gyeonghoeru_Batch_05_27071poly" then
		return "GY_Gyeonghoeru_Batch_05"
	elseif name == "GY_Gyeonghoeru_Batch_06_27061poly" then
		return "GY_Gyeonghoeru_Batch_06"
	elseif name == "GY_Gyeonghoeru_Batch_07_28981poly" then
		return "GY_Gyeonghoeru_Batch_07"
	end

	return nil
end

local function ProcessModel(instance)
	local normalizedName = GetNormalizedName(instance.Name)
	if not normalizedName then
		return
	end

	-- Every exported batch shares the same Blender origin. Add the same
	-- absolute world-space offset to preserve exact inter-batch assembly.
	for _, descendant in instance:GetDescendants() do
		if descendant:IsA("BasePart") then
			descendant.CFrame += TARGET_OFFSET
			descendant.CanCollide = false
			descendant.CanTouch = false
		end
	end

	instance.WorldPivot = CFrame.new(TARGET_OFFSET)
	instance.Name = normalizedName
end

BatchNormalizer.OnGenerate = function(parameters, targetContainer)
	-- A single imported batch can be injected as the target to avoid scanning
	-- unrelated large scene data. Workspace targeting remains supported.
	if workspace:IsA("Model") then
		ProcessModel(workspace)
		return
	end

	for _, instance in workspace:GetChildren() do
		if instance:IsA("Model") then
			ProcessModel(instance)
		end
	end
end

return BatchNormalizer
